"""숙소 예약 MCP 서버를 호출하는 Client입니다."""

from app.core.config import settings
from app.services.mcp_client import call_mcp_tool


def book_accommodation(payload: dict[str, object]) -> dict[str, object]:
    """예약 서버의 book_accommodation tool을 호출하고 결과를 반환합니다."""

    return call_mcp_tool(settings.booking_mcp_url, "book_accommodation", payload)
