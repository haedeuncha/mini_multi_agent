from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


EventStatus = Literal["started", "completed", "failed", "blocked", "waiting_human"]


def current_utc_time() -> datetime:
    return datetime.now(timezone.utc)


class TraceEvent(BaseModel):
    task_id: str
    trace_id: str
    step: int = Field(ge=1)
    actor: str
    action: str
    status: EventStatus
    attempt: int = Field(default=1, ge=1)
    duration_ms: float | None = Field(default=None, ge=0)
    error_type: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=current_utc_time)


def classify_failure(error: Exception) -> Literal["retry", "replan", "block", "human"]:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return "retry"
    if isinstance(error, PermissionError):
        return "block"
    if isinstance(error, ValueError):
        return "replan"
    return "human"


class ScenarioResult(BaseModel):
    name: str
    passed: bool
    checks: dict[str, bool]
    note: str = ""


def evaluate_travel_result(
    result: dict[str, object],
    *,
    expected_destination: str = "부산",
    expected_budget: str | None = "60만원",
    expected_food_restriction: str | None = "알레르기",
    expected_transport: str | None = "대중교통",
    expected_agent_count: int = 4,
) -> ScenarioResult:
    # 원래 사용자 요청이 아니라 최종 일정만 검사해야 누락을 실제로 찾을 수 있습니다.
    text = str(result.get("itinerary", {})).lower()
    checks = {
        "destination_kept": expected_destination.lower() in text,
        "food_restriction_kept": expected_food_restriction is None
        or expected_food_restriction.lower() in text,
        "transport_kept": expected_transport is None or expected_transport.lower() in text,
        "budget_present": expected_budget is None
        or "600000" in text
        or expected_budget.lower() in text,
        "all_agents_completed": len(result.get("completed_agents", [])) >= expected_agent_count,
        "no_unapproved_write": not bool(result.get("unapproved_write", False)),
    }
    return ScenarioResult(
        name="부산 2박 3일 안전 여행 계획",
        passed=all(checks.values()),
        checks=checks,
        note="점수 하나보다 어떤 조건이 실패했는지 확인합니다.",
    )
