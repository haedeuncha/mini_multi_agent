"""Lab 08: 같은 평가·Feedback 구조를 고객지원 답변에 적용한다."""

import asyncio
import json

from app.providers.registry import ProviderExecutionError, generate
from app.schemas.contracts import (
    EvaluationResult,
    SupportEvaluationRequest,
    WritingResult,
)


SUPPORT_CRITERIA = [
    {"criterion_key": "checks", "required_text": "확인 절차", "weight": 50, "mandatory": True},
    {"criterion_key": "no_false_claim", "required_text": "실제 변경을 완료하지 않았습니다", "weight": 50, "mandatory": True},
]


async def generate_with_retry(provider: str, prompt: str, schema: type):
    """일시적인 Provider 장애만 한 번 더 시도합니다."""
    for attempt in range(2):
        try:
            return await generate(provider, prompt, schema)
        except ProviderExecutionError as error:
            if not error.retryable or attempt == 1:
                raise
            await asyncio.sleep(error.retry_after_seconds or 1)


def evaluate_support_text(draft: WritingResult) -> tuple[int, list[str]]:
    passed = [item["criterion_key"] for item in SUPPORT_CRITERIA if item["required_text"] in draft.content]
    score = sum(item["weight"] for item in SUPPORT_CRITERIA if item["criterion_key"] in passed)
    failed = [item["criterion_key"] for item in SUPPORT_CRITERIA if item["criterion_key"] not in passed]
    return score, failed


async def run_support_evaluation(request: SupportEvaluationRequest) -> dict[str, object]:
    missing_instruction = (
        "첫 초안에서는 '실제 변경을 완료하지 않았습니다' 문구를 의도적으로 누락하세요."
        if request.demonstrate_revision
        else "처음부터 모든 기준을 충족하세요."
    )
    writer_prompt = f"""당신은 고객지원 Writer Agent입니다.
요청: {request.request}
평가 기준: {json.dumps(SUPPORT_CRITERIA, ensure_ascii=False)}
{missing_instruction}
WritingResult 형식으로 답변 초안을 작성하세요."""
    draft, writer_metadata = await generate_with_retry("openai", writer_prompt, WritingResult)
    trace = [{"step": 1, "actor": "support_writer_agent", "action": "write", "status": "completed", **writer_metadata}]

    # Writer 1회 + Evaluator 최대 4회 + Reviser 최대 3회 = LLM 최대 8회입니다.
    for round_number in range(1, 5):
        evaluator_prompt = f"""당신은 고객지원 Evaluator Agent입니다.
평가 기준: {json.dumps(SUPPORT_CRITERIA, ensure_ascii=False)}
초안: {draft.model_dump_json()}
부족한 기준과 수정 방법을 EvaluationResult 형식으로 반환하세요."""
        llm_evaluation, evaluator_metadata = await generate_with_retry(
            "openai", evaluator_prompt, EvaluationResult
        )
        score, failed = evaluate_support_text(draft)
        passed = score == 100 and not failed
        evaluation = EvaluationResult(
            passed=passed,
            score=score,
            feedback=llm_evaluation.feedback,
            passed_criteria=[item["criterion_key"] for item in SUPPORT_CRITERIA if item["criterion_key"] not in failed],
            failed_criteria=failed,
        )
        trace.append({"step": len(trace) + 1, "actor": "support_evaluator_agent", "action": "evaluate", "status": "passed" if passed else "failed", "round": round_number, "score": score, **evaluator_metadata})
        if passed:
            return {"status": "completed", "rounds": round_number, "score": score, "criteria": SUPPORT_CRITERIA, "draft": draft.model_dump(), "evaluation": evaluation.model_dump(), "trace": trace}
        if round_number == 4:
            return {"status": "quality_failed", "rounds": round_number, "score": score, "criteria": SUPPORT_CRITERIA, "draft": draft.model_dump(), "evaluation": evaluation.model_dump(), "trace": trace}

        reviser_prompt = f"""당신은 고객지원 Reviser Agent입니다.
현재 초안: {draft.model_dump_json()}
실패 기준: {failed}
Evaluator Feedback: {evaluation.feedback}
모든 평가 기준을 반영한 WritingResult 전체를 반환하세요."""
        draft, reviser_metadata = await generate_with_retry("openai", reviser_prompt, WritingResult)
        trace.append({"step": len(trace) + 1, "actor": "support_reviser_agent", "action": "revise", "status": "completed", "round": round_number, **reviser_metadata})

    raise RuntimeError("평가 반복이 종료되지 않았습니다.")
