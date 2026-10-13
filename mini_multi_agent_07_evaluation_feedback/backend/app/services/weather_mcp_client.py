"""외부 날씨 MCP 서버를 호출하는 Client입니다."""

from app.core.config import settings
from app.services.mcp_client import call_mcp_tool


def get_current_weather(destination: str) -> dict[str, object]:
    """목적지의 현재 날씨를 Weather MCP 서버에서 조회합니다."""

    return call_mcp_tool(settings.weather_mcp_url, "current_weather", {"destination": destination})
