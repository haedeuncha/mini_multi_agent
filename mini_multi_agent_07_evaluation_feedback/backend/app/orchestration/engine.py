""" 
[통합 실행 시나리오]
PostgreSQL에서 실제 평가 기준을 읽고 OpenAI Writer Agent가 여행 안내 초안을 만듭니다.
Gemma Evaluator Agent가 평가한 뒤 Python Quality Gate가 필수 문구와 점수를 다시
검사합니다. 실패하면 OpenAI Reviser Agent가 Feedback을 반영하고 최대 5회 안에서
재평가합니다. Provider의 일시적 오류는 각 호출마다 최대 2회만 Retry합니다.

Redis에는 화면 폴링용 현재 상태와 Trace를 저장하고, PostgreSQL에는 실행 결과와
회차별 점수·Feedback을 영구 저장합니다. 기준 통과, 최대 회차, Provider 실패 중
하나가 반드시 종료 조건이 됩니다.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from app.agents.evaluator_agent import evaluate_draft
from app.agents.registry import load_policies
from app.agents.reviser_agent import revise_draft
from app.agents.writer_agent import write_draft
from app.database import repository
from app.observability.tracker import EvaluationTracker
from app.orchestration.failure_policy import classify_failure
from app.schemas.contracts import EvaluationRunRequest


def new_run(request: EvaluationRunRequest) -> tuple[str, dict[str, object]]:
    run_id = str(uuid4())
    return run_id, {
        "run_id": run_id,
        "status": "queued",
        "current_stage": "queued",
        "current_actor": "orchestrator",
        "current_status": "waiting",
        "message": "Feedback Loop 실행을 기다리고 있습니다.",
        "progress": 0,
        "current_round": None,
        "result": None,
    }


async def execute_with_retry(
    operation: Callable[..., Awaitable[Any]],
    operation_args: tuple[object, ...],
    actor: str,
    stage: str,
    tracker: EvaluationTracker,
    round_number: int | None = None,
) -> tuple[object, dict[str, object]]:
    retry_policy = load_policies()["retry"]
    max_attempts = retry_policy["max_attempts"]
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation(*operation_args)
        except Exception as error:
            last_error = error
            decision = classify_failure(error, set(retry_policy["retryable_errors"]))
            tracker.record(
                stage,
                actor,
                "retrying" if decision == "retry" and attempt < max_attempts else "failed",
                f"{type(error).__name__}: {error}",
                progress=10,
                round_number=round_number,
                attempt=attempt,
                details={"failure_policy": decision, "max_attempts": max_attempts},
            )
            if decision != "retry" or attempt == max_attempts:
                raise
            retry_after = getattr(error, "retry_after_seconds", None)
            if retry_after:
                await asyncio.sleep(retry_after)

    raise RuntimeError(str(last_error))


async def run_feedback_workflow(run_id: str, state: dict[str, object], request: EvaluationRunRequest) -> None:
    tracker = EvaluationTracker(run_id, state)
    state["status"] = "running"
    last_score: int | None = None
    last_content: str | None = None

    try:
        repository.create_run(run_id, request.user_id, request.request)
        criteria = repository.list_criteria()
        if not criteria:
            raise ValueError("활성화된 평가 기준이 없습니다. 먼저 DB Seed를 적용하세요.")
        validate_criteria(criteria)
        tracker.record("criteria", "evaluation_repository", "completed", "PostgreSQL 평가 기준을 불러왔습니다.", progress=10, details={"count": len(criteria)})

        draft, writer_metadata = await execute_with_retry(
            write_draft,
            (request.request, criteria, request.demonstrate_revision),
            "writer_agent",
            "write",
            tracker,
        )
        last_content = draft.content
        tracker.record("write", "writer_agent", "completed", "OpenAI Writer Agent가 최초 초안을 작성했습니다.", progress=20, details=writer_metadata)

        max_rounds = load_policies()["feedback_loop"]["max_review_rounds"]
        for round_number in range(1, max_rounds + 1):
            evaluation, evaluator_metadata = await execute_with_retry(
                evaluate_draft,
                (draft, criteria),
                "evaluator_agent",
                "evaluate",
                tracker,
                round_number,
            )
            last_score = evaluation.score
            repository.save_round(run_id, round_number, draft.content, evaluation.model_dump(), evaluator_metadata)
            tracker.record(
                "evaluate",
                "evaluator_agent",
                "passed" if evaluation.passed else "failed",
                f"{round_number}회 평가 점수: {evaluation.score}",
                progress=20 + round_number * 14,
                round_number=round_number,
                details={**evaluator_metadata, **evaluation.model_dump()},
            )

            if evaluation.passed:
                result = {"rounds": round_number, "score": evaluation.score, "draft": draft.model_dump(), "evaluation": evaluation.model_dump()}
                repository.complete_run(run_id, "completed", evaluation.score, draft.content)
                tracker.finish("completed", result)
                return

            if round_number == max_rounds:
                result = {"rounds": round_number, "score": evaluation.score, "draft": draft.model_dump(), "evaluation": evaluation.model_dump(), "reason": "max_review_rounds"}
                repository.complete_run(run_id, "quality_failed", evaluation.score, draft.content)
                tracker.finish("quality_failed", result)
                return

            draft, reviser_metadata = await execute_with_retry(
                revise_draft,
                (draft, evaluation, criteria),
                "reviser_agent",
                "revise",
                tracker,
                round_number,
            )
            last_content = draft.content
            tracker.record(
                "revise",
                "reviser_agent",
                "completed",
                f"{round_number}회 Feedback을 반영했습니다.",
                progress=27 + round_number * 14,
                round_number=round_number,
                details={**reviser_metadata, "feedback": evaluation.feedback},
            )
    except Exception as error:
        decision = classify_failure(error)
        tracker.record("workflow", "orchestrator", "failed", str(error), progress=95, details={"failure_policy": decision, "error_type": type(error).__name__})
        try:
            repository.complete_run(run_id, "failed", last_score, last_content, str(error))
        except Exception:
            pass
        tracker.finish("failed", {"error": str(error), "failure_policy": decision})


def validate_criteria(criteria: list[dict[str, object]]) -> None:
    keys = [str(row.get("criterion_key", "")) for row in criteria]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("평가 기준 Key는 비어 있지 않고 중복되지 않아야 합니다.")
    if any(not str(row.get("required_text", "")).strip() for row in criteria):
        raise ValueError("모든 평가 기준에는 required_text가 필요합니다.")
    weights = [row.get("weight") for row in criteria]
    if any(not isinstance(weight, int) or weight <= 0 for weight in weights):
        raise ValueError("평가 기준 가중치는 양의 정수여야 합니다.")
    if sum(weights) != 100:
        raise ValueError(f"활성 평가 기준 가중치 합계는 100이어야 합니다: {sum(weights)}")
