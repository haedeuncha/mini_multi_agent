from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from shared.travel_contracts import AgentId


ToolName = Literal["get_weather", "search_places", "calculate_budget", "save_itinerary"]

TOOL_ALLOWLIST: dict[AgentId, set[ToolName]] = {
    "weather_agent": {"get_weather"},
    "place_agent": {"search_places"},
    "budget_agent": {"calculate_budget"},
    "itinerary_agent": {"save_itinerary"},
}
WRITE_TOOLS: set[ToolName] = {"save_itinerary"}


class ToolRequest(BaseModel):
    task_id: str
    user_id: str
    agent_id: AgentId
    tool_name: ToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = None


class Approval(BaseModel):
    task_id: str
    user_id: str
    tool_name: ToolName
    approved: bool


def authorize_tool(
    request: ToolRequest,
    *,
    expected_user_id: str,
    approval: Approval | None = None,
) -> None:
    if request.user_id != expected_user_id:
        raise PermissionError("다른 사용자의 Tool 요청입니다.")
    if request.tool_name not in TOOL_ALLOWLIST[request.agent_id]:
        raise PermissionError(f"{request.agent_id}에게 허용되지 않은 Tool입니다.")
    if request.tool_name in WRITE_TOOLS:
        if not request.idempotency_key:
            raise ValueError("변경 Tool에는 idempotency_key가 필요합니다.")
        if approval is None or not approval.approved:
            raise PermissionError("사용자 승인 전에는 변경 Tool을 실행할 수 없습니다.")
        if (
            approval.task_id != request.task_id
            or approval.user_id != request.user_id
            or approval.tool_name != request.tool_name
        ):
            raise PermissionError("현재 Tool 요청과 일치하지 않는 승인입니다.")


class IdempotencyRegistry:
    """개념 확인용 메모리 Registry. 실제 서비스에서는 Redis로 교체합니다."""

    def __init__(self) -> None:
        self._results: dict[tuple[str, str], object] = {}

    def execute_once(self, user_id: str, key: str, action) -> tuple[object, bool]:
        scoped_key = (user_id, key)
        if scoped_key in self._results:
            return self._results[scoped_key], False
        result = action()
        self._results[scoped_key] = result
        return result, True
