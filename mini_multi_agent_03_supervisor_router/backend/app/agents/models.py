from dataclasses import dataclass

@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    name: str
    goal: str
    description: str
    example_question: str
    instructions: str
    provider: str
    output_contract: str
    allowed_tools: frozenset[str] = frozenset()
    # [Workshop 2] 같은 업무의 Worker를 묶는 이름 (예: split). YAML에 없으면 빈 문자열.
    group: str = ""
