r"""Hotel MCP Server.

실행 명령:
    cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
    .\.venv\Scripts\Activate.ps1
    python .\mcp_hotel_server\main.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

mcp = FastMCP(
    "mini07-hotel-tools",
    host="127.0.0.1",
    port=int(os.getenv("HOTEL_MCP_PORT", "18011")),
    stateless_http=True,
    json_response=True,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

HOTEL_OPTIONS = [
    # 부산 현대 미술관 주변
    {"hotel_id": "hotel-artstay", "place_id": "place-busan-museum", "name": "아트스테이 호텔", "nightly_price": 88000, "distance_minutes": 8, "summary": "미술관 근처의 조용한 숙소입니다."},
    {"hotel_id": "hotel-museum-bay", "place_id": "place-busan-museum", "name": "뮤지엄 베이 호텔", "nightly_price": 105000, "distance_minutes": 12, "summary": "미술관과 을숙도 이동이 편리한 숙소입니다."},
    {"hotel_id": "hotel-art-budget", "place_id": "place-busan-museum", "name": "아트 버짓 스테이", "nightly_price": 69000, "distance_minutes": 15, "summary": "합리적인 가격으로 머물 수 있는 수업용 숙소입니다."},

    # 광안리 해변 주변
    {"hotel_id": "hotel-oceanview", "place_id": "place-gwangalli", "name": "오션뷰 스테이", "nightly_price": 132000, "distance_minutes": 5, "summary": "해변 접근성이 좋은 숙소입니다."},
    {"hotel_id": "hotel-bridge-view", "place_id": "place-gwangalli", "name": "브리지뷰 호텔", "nightly_price": 158000, "distance_minutes": 7, "summary": "광안대교 야경을 보기 좋은 숙소입니다."},
    {"hotel_id": "hotel-gwangalli-budget", "place_id": "place-gwangalli", "name": "광안리 라이트 스테이", "nightly_price": 82000, "distance_minutes": 11, "summary": "해변 주변의 가격이 비교적 낮은 숙소입니다."},

    # 전포 카페 거리 주변
    {"hotel_id": "hotel-cafehub", "place_id": "place-jeonpo", "name": "카페허브 비즈니스 호텔", "nightly_price": 76000, "distance_minutes": 6, "summary": "전포 카페 거리와 가까운 합리적인 숙소입니다."},
    {"hotel_id": "hotel-jeonpo-urban", "place_id": "place-jeonpo", "name": "전포 어반 호텔", "nightly_price": 94000, "distance_minutes": 8, "summary": "카페 거리와 서면 이동이 편리한 숙소입니다."},
    {"hotel_id": "hotel-jeonpo-house", "place_id": "place-jeonpo", "name": "전포 게스트하우스", "nightly_price": 58000, "distance_minutes": 10, "summary": "가볍게 머물기 좋은 수업용 게스트하우스입니다."},
]


@mcp.tool(annotations=READ_ONLY)
def search_hotels(places: list[dict[str, object]]) -> dict[str, object]:
    """장소 후보 주변 숙소를 조회합니다."""

    print("[Hotel MCP] 숙소 조회 요청 수신", places, flush=True)
    place_name_by_id = {str(place["place_id"]): str(place["name"]) for place in places}
    place_score_by_id = {str(place["place_id"]): int(place.get("score", 0)) for place in places}
    hotels: list[dict[str, object]] = []
    for hotel in HOTEL_OPTIONS:
        place_id = str(hotel["place_id"])
        if place_id not in place_name_by_id:
            continue
        hotels.append(
            {
                **hotel,
                "near_place": place_name_by_id[place_id],
                "recommendation_score": max(0, place_score_by_id[place_id] - int(hotel["distance_minutes"])),
            }
        )
    hotels = sorted(hotels, key=lambda item: int(item["recommendation_score"]), reverse=True)
    print("[Hotel MCP] 숙소 후보 반환", hotels, flush=True)
    return {"hotels": hotels}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
