r"""Weather MCP Server.

실행 명령:
    cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
    .\.venv\Scripts\Activate.ps1
    python .\mcp_weather_server\main.py
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

mcp = FastMCP(
    "mini07-weather-tools",
    host="127.0.0.1",
    port=int(os.getenv("WEATHER_MCP_PORT", "18012")),
    stateless_http=True,
    json_response=True,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

CITY_COORDINATES = {
    "부산": {"latitude": 35.1796, "longitude": 129.0756, "name": "부산"},
    "서울": {"latitude": 37.5665, "longitude": 126.9780, "name": "서울"},
    "제주": {"latitude": 33.4996, "longitude": 126.5312, "name": "제주"},
}

RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
WEATHER_LABELS = {
    0: "맑음",
    1: "대체로 맑음",
    2: "부분적으로 흐림",
    3: "흐림",
    45: "안개",
    48: "짙은 안개",
    51: "약한 이슬비",
    53: "이슬비",
    55: "강한 이슬비",
    61: "약한 비",
    63: "비",
    65: "강한 비",
    80: "약한 소나기",
    81: "소나기",
    82: "강한 소나기",
    95: "뇌우",
}


@mcp.tool(annotations=READ_ONLY)
def current_weather(destination: str = "부산") -> dict[str, object]:
    """목적지의 현재 날씨를 Open-Meteo에서 조회합니다."""

    if destination not in CITY_COORDINATES:
        raise ValueError(f"날씨를 조회할 수 없는 도시입니다: {destination}")
    city = CITY_COORDINATES[destination]
    print("[Weather MCP] 실제 날씨 조회 요청", {"destination": destination, **city}, flush=True)
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "current": "temperature_2m,weather_code,precipitation",
                "timezone": "Asia/Seoul",
            },
            timeout=10,
        )
        response.raise_for_status()
        current = response.json()["current"]
        code = int(current.get("weather_code", -1))
        result = {
            "destination": city["name"],
            "temperature_c": current.get("temperature_2m"),
            "weather_code": code,
            "weather_label": WEATHER_LABELS.get(code, "알 수 없음"),
            "precipitation_mm": current.get("precipitation", 0),
            "is_raining": code in RAIN_CODES or float(current.get("precipitation", 0) or 0) > 0,
            "source": "Open-Meteo",
            "observed_at": current.get("time"),
        }
    except Exception as error:
        result = {
            "destination": city["name"],
            "temperature_c": None,
            "weather_code": None,
            "weather_label": "날씨 조회 실패 - 수업용 fallback",
            "precipitation_mm": None,
            "is_raining": False,
            "source": "fallback",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
        }
    print("[Weather MCP] 실제 날씨 조회 결과", result, flush=True)
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
