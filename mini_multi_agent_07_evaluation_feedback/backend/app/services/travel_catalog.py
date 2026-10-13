"""통합 여행 예약 예제에서 사용하는 수업용 장소 데이터입니다.

이 파일에는 AI 서비스 Backend가 직접 관리하는 장소 후보만 둡니다. 숙소 정보는
외부 숙소 조회 시스템이라고 가정한 `mcp_hotel_server`가 가지고 있습니다.
"""

PLACE_OPTIONS = [
    {
        "place_id": "place-busan-museum",
        "name": "부산 현대 미술관",
        "destination": "부산",
        "weather_fit": "rainy",
        "summary": "비 오는 날에도 이동 부담이 적고 실내 관람이 가능한 장소입니다.",
        "tags": ["실내", "전시", "조용함"],
    },
    {
        "place_id": "place-gwangalli",
        "name": "광안리 해변",
        "destination": "부산",
        "weather_fit": "sunny",
        "summary": "날씨가 맑을 때 산책과 야경 감상에 적합한 장소입니다.",
        "tags": ["바다", "야경", "산책"],
    },
    {
        "place_id": "place-jeonpo",
        "name": "전포 카페 거리",
        "destination": "부산",
        "weather_fit": "any",
        "summary": "실내 카페와 식당 선택지가 많아 날씨 영향이 비교적 적습니다.",
        "tags": ["맛집", "카페", "실내"],
    },
]


def recommend_places(destination: str, weather: str, preferences: list[str]) -> list[dict[str, object]]:
    """목적지·날씨·취향에 맞는 장소 후보를 점수와 함께 반환합니다."""

    normalized_weather = weather.lower()
    rainy = "비" in weather or "rain" in normalized_weather
    sunny = "맑" in weather or "sun" in normalized_weather
    preferred = set(preferences)
    results: list[dict[str, object]] = []

    for place in PLACE_OPTIONS:
        if place["destination"] != destination:
            continue

        score = 40
        if place["weather_fit"] == "any":
            score += 20
        if rainy and place["weather_fit"] == "rainy":
            score += 30
        if sunny and place["weather_fit"] == "sunny":
            score += 30
        score += 10 * len(preferred.intersection(place["tags"]))

        results.append({**place, "score": min(score, 100)})

    return sorted(results, key=lambda item: item["score"], reverse=True)
