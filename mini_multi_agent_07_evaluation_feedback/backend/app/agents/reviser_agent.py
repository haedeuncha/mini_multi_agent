import json

from app.agents.registry import REVISER_AGENT, provider_for_agent
from app.providers.registry import generate
from app.schemas.contracts import EvaluationResult, WritingResult


async def revise_draft(
    draft: WritingResult,
    evaluation: EvaluationResult,
    criteria: list[dict[str, object]],
) -> tuple[WritingResult, dict[str, object]]:
    prompt = f"""당신은 {REVISER_AGENT.name}입니다.
Goal: {REVISER_AGENT.goal}
Instructions: {REVISER_AGENT.instructions}

현재 초안:
{draft.model_dump_json()}

Evaluator Feedback:
{evaluation.feedback}

전체 평가 기준:
{json.dumps(criteria, ensure_ascii=False, default=str)}

WritingResult 형식으로 수정된 전체 초안을 반환하세요."""
    return await generate(provider_for_agent(REVISER_AGENT.agent_id), prompt, WritingResult)
