from typing import Literal
from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentId = Literal["weather_agent", "place_agent", "budget_agent", "itinerary_agent", "safety_agent"]


class TravelPlanDraft(BaseModel):
    destination: str
    days: int = Field(ge=1, le=30)
    summary: str
    recommendations: list[str] = Field(min_length=1, max_length=8)
    cautions: list[str] = Field(default_factory=list, max_length=8)


class LearningAgentResult(BaseModel):
    """01 단원의 여러 역할이 공통으로 사용하는 작은 출력 계약입니다."""

    agent_id: str
    summary: str
    details: list[str] = Field(default_factory=list, max_length=8)
    completed: bool = True


class LearningRouteDecision(BaseModel):
    selected_agent: Literal["refund_agent", "delivery_agent", "technical_support_agent"]
    reason: str


class SupportRouteDecision(BaseModel):
    """고객지원 Router가 한 Worker 또는 추가 정보 요청을 선택하는 계약입니다."""

    agent_id: Literal["router_agent"] = "router_agent"
    selected_agent: Literal[
        "delivery_agent",
        "refund_agent",
        "technical_support_agent",
        "request_information",
    ]
    reason: str
    missing_information: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def missing_information_must_match_route(self) -> "SupportRouteDecision":
        if self.selected_agent == "request_information" and not self.missing_information:
            raise ValueError("추가 정보 요청에는 missing_information이 필요합니다.")
        if self.selected_agent != "request_information" and self.missing_information:
            raise ValueError("Worker를 선택한 경우 missing_information은 비어 있어야 합니다.")
        return self


class SupervisorDecision(BaseModel):
    """Supervisor가 현재 State를 보고 반환하는 다음 행동 계약입니다."""

    agent_id: Literal["supervisor_agent"] = "supervisor_agent"
    next_agent: Literal["analyst_agent", "developer_agent", "reviewer_agent", "finish"]
    instruction: str
    context_keys: list[str] = Field(default_factory=list, max_length=5)
    reason: str


class HandoffContext(BaseModel):
    """LLM이 전달할 수 있는 최소 주문 Context만 허용합니다."""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = None
    issue: str | None = None


class HandoffDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["support_agent"] = "support_agent"
    handoff_required: bool
    target_agent: Literal["refund_agent"] | None = None
    reason: str
    handoff_context: HandoffContext = Field(default_factory=HandoffContext)

    @model_validator(mode="after")
    def handoff_fields_must_match_decision(self) -> "HandoffDecision":
        context = self.handoff_context
        if self.handoff_required:
            if self.target_agent is None:
                raise ValueError("Handoff가 필요하면 target_agent가 있어야 합니다.")
            if not context.order_id or not context.issue:
                raise ValueError("Handoff에는 order_id와 issue가 모두 필요합니다.")
        elif self.target_agent is not None or context.order_id is not None or context.issue is not None:
            raise ValueError("Handoff가 필요하지 않으면 대상과 Context가 비어 있어야 합니다.")
        return self


class EvaluationResult(BaseModel):
    agent_id: Literal["evaluator_agent"] = "evaluator_agent"
    passed: bool
    feedback: str
    missing_requirements: list[str] = Field(default_factory=list, max_length=5)


class SpecialistResult(BaseModel):
    agent_id: AgentId
    goal: str
    summary: str
    recommendations: list[str] = Field(min_length=1, max_length=6)
    missing_information: list[str] = Field(default_factory=list, max_length=5)
    completed: bool


class WeatherResult(BaseModel):
    """Weather Agent만 반환할 수 있는 최소 결과 계약입니다."""

    agent_id: Literal["weather_agent"] = "weather_agent"
    forecast_summary: str
    cautions: list[str] = Field(default_factory=list, max_length=5)
    source_confirmed: bool


class PlaceResult(BaseModel):
    """Place Agent의 장소 후보와 선택 근거 계약입니다."""

    agent_id: Literal["place_agent"] = "place_agent"
    places: list[str] = Field(min_length=1, max_length=6)
    selection_reason: str


class SafetyResult(BaseModel):
    """Safety Agent의 위험 요소와 확인 행동 계약입니다."""

    agent_id: Literal["safety_agent"] = "safety_agent"
    risks: list[str] = Field(min_length=1, max_length=6)
    required_actions: list[str] = Field(min_length=1, max_length=6)


BudgetBreakdown = TypedDict(
    "BudgetBreakdown",
    {"교통": int, "숙박": int, "식비": int, "예비비": int},
)


class BudgetResult(BaseModel):
    """Budget Agent의 항목별 금액과 합계 계약입니다."""

    agent_id: Literal["budget_agent"] = "budget_agent"
    currency: Literal["KRW"] = "KRW"
    breakdown: BudgetBreakdown
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def total_must_match_breakdown(self) -> "BudgetResult":
        if any(amount < 0 for amount in self.breakdown.values()):
            raise ValueError("예산 항목은 음수일 수 없습니다.")
        if sum(self.breakdown.values()) != self.total:
            raise ValueError("예산 합계가 항목별 금액의 합과 다릅니다.")
        return self


class ItineraryResult(BaseModel):
    """Itinerary Agent의 날짜별 일정 계약입니다."""

    agent_id: Literal["itinerary_agent"] = "itinerary_agent"
    destination: str
    day_plans: list[str] = Field(min_length=1, max_length=30)
    applied_constraints: list[str] = Field(default_factory=list, max_length=10)


class ValidationResult(BaseModel):
    """최종 일정의 조건 누락과 충돌을 보고하는 계약입니다."""

    agent_id: Literal["validation_agent"] = "validation_agent"
    passed: bool
    issues: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def passed_result_cannot_have_issues(self) -> "ValidationResult":
        if self.passed and self.issues:
            raise ValueError("통과한 검증 결과에는 issue가 없어야 합니다.")
        if not self.passed and not self.issues:
            raise ValueError("실패한 검증 결과에는 issue가 필요합니다.")
        return self


class RouteDecision(BaseModel):
    selected_agents: list[AgentId] = Field(min_length=1, max_length=4)
    reason: str
    missing_information: list[str] = Field(default_factory=list, max_length=5)


SPECIALIST_GOALS: dict[AgentId, str] = {
    "weather_agent": "날씨 관점에서 필요한 준비와 확인 항목을 정리한다.",
    "place_agent": "사용자 조건에 맞는 장소 탐색 기준과 후보를 정리한다.",
    "budget_agent": "여행 예산 항목과 계산에 필요한 정보를 정리한다.",
    "itinerary_agent": "검증된 정보를 날짜별 일정 초안으로 구성한다.",
    "safety_agent": "알레르기와 이동 조건에서 주의할 사항을 독립적으로 정리한다.",
}
