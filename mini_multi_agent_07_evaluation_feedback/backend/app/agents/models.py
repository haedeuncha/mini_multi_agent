from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    name: str
    goal: str
    description: str
    instructions: str
    provider: str
