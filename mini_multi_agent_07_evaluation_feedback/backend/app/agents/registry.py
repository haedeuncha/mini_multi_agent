from pathlib import Path

import yaml

from app.agents.models import AgentProfile
from app.providers.registry import PROVIDERS


POLICY_PATH = Path(__file__).parent / "definitions" / "evaluation_policies.yaml"

WRITER_AGENT = AgentProfile(
    agent_id="writer_agent",
    name="OpenAI Writer Agent",
    goal="사용자 요청과 평가 기준을 반영한 여행 안내 초안을 작성한다.",
    description="최초 결과를 만드는 Agent이며 자신의 결과를 직접 평가하지 않습니다.",
    instructions="제공된 요구사항만 사용하고 실제 결제나 예약이 완료됐다고 주장하지 마세요.",
    provider="openai",
)

EVALUATOR_AGENT = AgentProfile(
    agent_id="evaluator_agent",
    name="Gemma Evaluator Agent",
    goal="Writer 결과를 독립된 기준으로 평가하고 구체적인 Feedback을 작성한다.",
    description="평가만 수행하며 초안을 직접 수정하지 않습니다.",
    instructions="각 기준의 통과 여부와 수정 가능한 Feedback을 구조화 결과로 반환하세요.",
    provider="gemma",
)

REVISER_AGENT = AgentProfile(
    agent_id="reviser_agent",
    name="OpenAI Reviser Agent",
    goal="Evaluator Feedback을 반영해 실패한 기준만 수정한다.",
    description="최대 반복 횟수 안에서 초안을 개선합니다.",
    instructions="기존에 통과한 내용을 보존하고 실패 기준과 Feedback을 정확히 반영하세요.",
    provider="openai",
)

AGENTS = {agent.agent_id: agent for agent in [WRITER_AGENT, EVALUATOR_AGENT, REVISER_AGENT]}


def load_policies() -> dict[str, object]:
    with POLICY_PATH.open(encoding="utf-8") as policy_file:
        policies = yaml.safe_load(policy_file)
    if not isinstance(policies, dict):
        raise ValueError("evaluation_policies.yaml 형식이 올바르지 않습니다.")
    required_sections = {"feedback_loop", "retry", "quality_gate"}
    missing = required_sections - set(policies)
    if missing:
        raise ValueError(f"평가 Policy 필수 Section 누락: {sorted(missing)}")
    feedback = policies["feedback_loop"]
    if not isinstance(feedback.get("max_review_rounds"), int) or not 1 <= feedback["max_review_rounds"] <= 10:
        raise ValueError("max_review_rounds는 1~10이어야 합니다.")
    for agent_id, key in {"writer_agent": "writer_provider", "evaluator_agent": "evaluator_provider", "reviser_agent": "reviser_provider"}.items():
        provider = feedback.get(key)
        if provider not in PROVIDERS:
            raise ValueError(f"{agent_id}의 Provider가 지원 목록에 없습니다: {provider}")
        if provider != AGENTS[agent_id].provider:
            raise ValueError(f"{agent_id}의 Python/YAML Provider가 다릅니다: python={AGENTS[agent_id].provider}, yaml={provider}")
    retry = policies["retry"]
    if not isinstance(retry.get("max_attempts"), int) or not 1 <= retry["max_attempts"] <= 5:
        raise ValueError("retry.max_attempts는 1~5여야 합니다.")
    retryable_errors = retry.get("retryable_errors")
    if not isinstance(retryable_errors, list) or not retryable_errors or not all(isinstance(name, str) and name for name in retryable_errors):
        raise ValueError("retry.retryable_errors에는 오류 이름이 하나 이상 필요합니다.")
    gate = policies["quality_gate"]
    if not isinstance(gate.get("minimum_score"), int) or not 0 <= gate["minimum_score"] <= 100:
        raise ValueError("quality_gate.minimum_score는 0~100이어야 합니다.")
    return policies


def provider_for_agent(agent_id: str) -> str:
    policy_keys = {
        "writer_agent": "writer_provider",
        "evaluator_agent": "evaluator_provider",
        "reviser_agent": "reviser_provider",
    }
    if agent_id not in policy_keys:
        raise ValueError(f"Provider 정책이 없는 Agent입니다: {agent_id}")
    return load_policies()["feedback_loop"][policy_keys[agent_id]]


def registry_view() -> dict[str, object]:
    return {
        "agents": {
            agent_id: {
                "name": agent.name,
                "goal": agent.goal,
                "description": agent.description,
                "default_provider": agent.provider,
                "effective_provider": provider_for_agent(agent_id),
            }
            for agent_id, agent in AGENTS.items()
        },
        "policies": load_policies(),
    }


# 잘못된 Provider·반복·점수 정책은 요청 처리 전 애플리케이션 시작 시 차단합니다.
load_policies()
