import json

from app.agents.registry import EVALUATOR_AGENT, load_policies, provider_for_agent
from app.providers.registry import generate
from app.schemas.contracts import EvaluationResult, WritingResult


def deterministic_checks(draft: WritingResult, criteria: list[dict[str, object]]) -> tuple[list[str], int]:
    passed_keys = [row["criterion_key"] for row in criteria if row["required_text"] in draft.content]
    score = sum(row["weight"] for row in criteria if row["criterion_key"] in passed_keys)
    return passed_keys, min(score, 100)


async def evaluate_draft(draft: WritingResult, criteria: list[dict[str, object]]) -> tuple[EvaluationResult, dict[str, object]]:
    prompt = f"""당신은 {EVALUATOR_AGENT.name}입니다.
Goal: {EVALUATOR_AGENT.goal}
Instructions: {EVALUATOR_AGENT.instructions}

평가 기준:
{json.dumps(criteria, ensure_ascii=False, default=str)}

평가할 초안:
{draft.model_dump_json()}

EvaluationResult 형식으로 반환하세요."""
    llm_result, metadata = await generate(provider_for_agent(EVALUATOR_AGENT.agent_id), prompt, EvaluationResult)

    passed_keys, deterministic_score = deterministic_checks(draft, criteria)
    mandatory_keys = {row["criterion_key"] for row in criteria if row["mandatory"]}
    failed_keys = [row["criterion_key"] for row in criteria if row["criterion_key"] not in passed_keys]
    policies = load_policies()["quality_gate"]
    mandatory_passed = mandatory_keys.issubset(set(passed_keys))
    passed = deterministic_score >= policies["minimum_score"] and mandatory_passed

    feedback = llm_result.feedback
    if failed_keys:
        missing_texts = [row["required_text"] for row in criteria if row["criterion_key"] in failed_keys]
        feedback = f"다음 기준을 반영하세요: {', '.join(missing_texts)}. LLM Feedback: {feedback}"

    final_result = EvaluationResult(
        passed=passed,
        score=deterministic_score,
        feedback=feedback,
        passed_criteria=passed_keys,
        failed_criteria=failed_keys,
    )
    metadata["llm_score"] = llm_result.score
    metadata["python_gate_score"] = deterministic_score
    return final_result, metadata
