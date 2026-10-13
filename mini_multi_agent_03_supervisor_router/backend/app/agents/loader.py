"""반복되는 Worker 선언을 YAML에서 AgentProfile로 변환한다."""

from pathlib import Path

import yaml

from app.agents.models import AgentProfile

DEFINITION_FILE = Path(__file__).resolve().parent / "definitions" / "workers.yaml"


def load_worker_agents() -> dict[str, AgentProfile]:
    document = yaml.safe_load(DEFINITION_FILE.read_text(encoding="utf-8"))
    agents = {}
    for agent_id, config in document["workers"].items():
        missing = [key for key in REQUIRED_KEYS if key not in config]
        if missing:
            raise ValueError(f"{agent_id}: YAML 필수 항목 누락 {missing}")
        agents[agent_id] = AgentProfile(
            agent_id=agent_id,
            name=config["name"],
            goal=config["goal"],
            description=config["description"],
            example_question=config["example_question"],
            instructions=config["instructions"].strip(),
            provider=config["provider"],
            output_contract=config["output_contract"],
            allowed_tools=frozenset(config.get("allowed_tools", [])),
            group=config.get("group", ""),  # [Workshop 2] Lab 10 Worker 묶음
        )
    validate_worker_agents(agents)
    return agents


# [Workshop 2] YAML 오타를 서버 시작 시점에 잡는다.
SUPPORTED_PROVIDERS = {"openai", "gemini", "ollama", "gemma"}
REQUIRED_KEYS = ("name", "goal", "description", "example_question", "instructions", "provider", "output_contract")


def validate_worker_agents(agents: dict[str, AgentProfile]) -> None:
    for agent_id, profile in agents.items():
        if profile.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"{agent_id}: 지원하지 않는 provider {profile.provider}")
        if not agent_id.endswith("_agent"):
            raise ValueError(f"{agent_id}: Agent ID는 _agent로 끝나야 합니다.")
