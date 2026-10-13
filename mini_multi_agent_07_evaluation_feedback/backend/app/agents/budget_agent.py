"""09 통합 여행 예약에서 금액을 결정적으로 계산하는 Python Agent입니다."""


def calculate_trip_budget(hotel: dict[str, object], nights: int, guest_count: int) -> dict[str, object]:
    """숙박비와 수업용 예상 비용을 같은 계산식으로 매번 정확하게 계산합니다."""

    lodging = int(hotel["nightly_price"]) * nights
    travel_days = nights + 1
    food = 30000 * guest_count * travel_days
    transport = 20000 * guest_count
    activity = 15000 * guest_count
    total = lodging + food + transport + activity
    return {
        "lodging": lodging,
        "food": food,
        "transport": transport,
        "activity": activity,
        "total": total,
        "currency": "KRW",
        "notice": "숙박비 외 항목은 수업용 예상 금액이며 실제 금액은 달라질 수 있습니다.",
    }
