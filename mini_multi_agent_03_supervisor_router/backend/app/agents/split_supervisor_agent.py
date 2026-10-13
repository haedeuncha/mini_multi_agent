"""[Workshop 2] Lab 10 · 공정 N빵 정산의 다음 Worker를 선택하는 Supervisor.

핵심 의사결정 Agent이므로 YAML이 아닌 Python에 둔다(incident_supervisor_agent.py와 같은 방식).
Supervisor는 다음 Worker를 '제안'만 하고, 허용 전이는 split_flow.py의 Python이 검사한다.
"""

from app.agents.models import AgentProfile


SPLIT_SUPERVISOR_AGENT = AgentProfile(
    agent_id="split_supervisor_agent",
    name="정산 Supervisor Agent",
    goal="검증된 정산 State를 보고 다음 Worker 또는 종료를 제안한다.",
    description="영수증 → 상황 → 분류 → (Python 계산) → 설명 순서를 State로 판단한다.",
    example_question="GATHER-0930 모임 비용을 공정하게 나눠 줘.",
    instructions="""Worker 업무를 대신하지 마세요. 금액을 계산하지 마세요.
현재 State와 Python이 허용한 다음 행동을 확인하고 그 Agent 하나 또는 finish를 선택하세요.
""",
    provider="openai",
    output_contract="SplitSupervisorDecision",
    group="split",
)
