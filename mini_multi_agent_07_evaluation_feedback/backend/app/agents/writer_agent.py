import json

from app.agents.registry import WRITER_AGENT, provider_for_agent
from app.providers.registry import generate
from app.schemas.contracts import WritingResult


async def write_draft(
    request: str,
    criteria: list[dict[str, object]],
    demonstrate_revision: bool,
) -> tuple[WritingResult, dict[str, object]]:
    demonstration_instruction = (
        "Feedback Loop 학습을 위해 최초 초안에서는 approval_boundary 기준 하나를 의도적으로 누락하세요."
        if demonstrate_revision
        else "처음부터 모든 평가 기준을 충족하도록 작성하세요."
    )
    prompt = f"""당신은 {WRITER_AGENT.name}입니다.
Goal: {WRITER_AGENT.goal}
Instructions: {WRITER_AGENT.instructions}

사용자 요청:
{request}

평가 기준:
{json.dumps(criteria, ensure_ascii=False, default=str)}

수업 실행 조건:
{demonstration_instruction}

WritingResult 형식으로 여행 안내 초안을 작성하세요."""
    return await generate(provider_for_agent(WRITER_AGENT.agent_id), prompt, WritingResult)
