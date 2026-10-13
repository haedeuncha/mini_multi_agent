"""외부 숙소 조회 MCP 서버를 호출하는 Client입니다."""

from app.core.config import settings
from app.services.mcp_client import call_mcp_tool


def search_hotels_for_places(places: list[dict[str, object]]) -> list[dict[str, object]]:
    """추천 장소 목록을 Hotel MCP 서버로 보내 숙소 후보를 조회합니다."""

    result = call_mcp_tool(settings.hotel_mcp_url, "search_hotels", {"places": places})
    return result["hotels"]
