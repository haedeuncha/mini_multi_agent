"""09의 여행 가이드를 OpenAI로 작성하고 Python 기준으로 검사합니다."""

import json

from app.providers.registry import generate
from app.schemas.contracts import TravelGuideResult


def evaluate_travel_guide(
    guide: TravelGuideResult,
    place: dict[str, object],
    hotel: dict[str, object],
    nights: int,
) -> dict[str, object]:
    """LLM 점수 대신 필수 내용의 실제 포함 여부를 Python으로 판정합니다."""

    combined = " ".join([guide.title, guide.weather_tip, guide.notice, *[item.guide for item in guide.schedule]])
    checks = {
        "selected_place": str(place["name"]) in combined,
        "selected_hotel": str(hotel["name"]) in combined,
        "estimated_budget_notice": "예상 금액" in combined,
        "final_approval_notice": "최종 승인" in combined,
        "schedule_days": len(guide.schedule) >= nights + 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failed,
        "score": round(100 * sum(checks.values()) / len(checks)),
        "failed_criteria": failed,
        "feedback": "모든 필수 항목을 포함했습니다." if not failed else f"다음 항목을 보완하세요: {', '.join(failed)}",
    }


async def create_evaluated_travel_guide(
    place: dict[str, object],
    hotel: dict[str, object],
    budget: dict[str, object],
    nights: int,
    weather: str,
) -> tuple[TravelGuideResult, dict[str, object], list[dict[str, object]]]:
    """OpenAI 초안을 검사하고, 실패할 때만 Feedback으로 한 번 수정합니다."""

    context = {
        "destination": place["destination"],
        "weather": weather,
        "place": place["name"],
        "hotel": hotel["name"],
        "nights": nights,
        "budget": budget,
    }
    prompt = f"""당신은 여행 Guide Writer Agent입니다.
다음 여행 조건으로 {nights}박 {nights + 1}일 가이드를 작성하세요.
조건: {json.dumps(context, ensure_ascii=False)}
선택 장소와 숙소 이름, '예상 금액', '최종 승인' 문구를 반드시 포함하세요.
TravelGuideResult 형식으로 반환하세요."""
    guide, metadata = await generate("openai", prompt, TravelGuideResult)
    evaluations = [evaluate_travel_guide(guide, place, hotel, nights)]

    if not evaluations[0]["passed"]:
        revise_prompt = f"""당신은 여행 Guide Reviser Agent입니다.
현재 가이드: {guide.model_dump_json()}
Python Quality Gate Feedback: {evaluations[0]['feedback']}
여행 조건: {json.dumps(context, ensure_ascii=False)}
누락 항목을 모두 반영한 TravelGuideResult 전체를 반환하세요."""
        guide, metadata = await generate("openai", revise_prompt, TravelGuideResult)
        evaluations.append(evaluate_travel_guide(guide, place, hotel, nights))

    return guide, metadata, evaluations
