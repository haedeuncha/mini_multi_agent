"""Labs 09~11: 통합 여행 예약, 이력 조회와 예약 부분 복구 예제입니다.

이 파일은 07 과정의 핵심 주제인 평가, 피드백, 실패 처리, 추적을 하나의 업무 흐름으로
보여 줍니다. AI 서비스 Backend는 장소 추천과 전체 흐름 조율을 담당하고, 숙소 조회와
예약 처리는 각각 별도 MCP 역할 서버가 담당합니다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.agents.budget_agent import calculate_trip_budget
from app.agents.travel_guide_agent import create_evaluated_travel_guide
from app.orchestration.failure_policy import classify_failure
from app.schemas.contracts import BookingRecoveryDemoRequest, TravelBookingConfirmRequest, TravelBookingStartRequest, TravelPlaceSelectRequest, TravelPlanApprovalRequest
from app.services.booking_mcp_client import book_accommodation
from app.services.hotel_mcp_client import search_hotels_for_places
from app.services.travel_catalog import recommend_places
from app.services.weather_mcp_client import get_current_weather
from app.storage.redis_store import append_event, load_events, load_snapshot, save_snapshot

HotelSearcher = Callable[[list[dict[str, object]]], list[dict[str, object]]]


def booking_failure_message(error: Exception) -> str:
    """예약 실패 원인을 학생이 조치할 수 있는 안전한 문장으로 바꿉니다."""

    raw = str(error).lower()
    if any(text in raw for text in ("connect", "connection", "refused", "all connection attempts failed")):
        return "Booking MCP 서버에 연결할 수 없습니다. 서버를 다시 실행하세요."
    if any(text in raw for text in ("validation", "unexpected", "extra inputs", "unknown argument", "arguments")):
        return "실행 중인 Booking MCP가 이전 Tool 형식입니다. Booking MCP 서버를 종료한 뒤 다시 실행하세요."
    if any(text in raw for text in ("undefinedcolumn", "does not exist", "total_budget", "travel_guide", "plan_approved_at", "booking_approved_at")):
        return "예약 테이블 스키마가 최신 상태가 아닙니다. python .\\sql\\apply_schema.py를 실행하세요."
    return f"Booking MCP 또는 PostgreSQL 처리 실패: {type(error).__name__}"


def make_event(sequence: int, stage: str, actor: str, status: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    """화면에서 읽기 쉬운 Trace Event를 만듭니다.

    details에는 API Key, 비밀번호, 인증 Token, 전체 Prompt 원문,
    불필요한 개인정보를 넣지 않습니다.
    """

    return {
        "sequence": sequence,
        "stage": stage,
        "actor": actor,
        "status": status,
        "round_number": None,
        "attempt": 1,
        "message": message,
        "details": details or {},
    }


def evaluate_place_recommendation(places: list[dict[str, object]], weather: str) -> dict[str, object]:
    """장소 추천이 날씨 조건을 반영했는지 간단히 평가합니다."""

    if not places:
        return {"passed": False, "score": 0, "feedback": "추천 장소가 없습니다.", "failed_criteria": ["place_exists"]}

    top_place = places[0]
    normalized_weather = weather.lower()
    rainy = "비" in weather or "rain" in normalized_weather
    sunny = "맑" in weather or "sun" in normalized_weather
    if rainy:
        allowed_weather_fits = {"rainy", "any"}
    elif sunny:
        allowed_weather_fits = {"sunny", "any"}
    else:
        # 흐림처럼 실내·실외를 단정하기 어려운 날씨에는 날씨 영향을 적게 받는 장소를 우선합니다.
        allowed_weather_fits = {"any"}
    weather_matched = top_place["weather_fit"] in allowed_weather_fits
    score = 100 if weather_matched else 60
    failed = [] if weather_matched else ["weather_fit"]
    feedback = (
        "현재 날씨에 어울리는 장소가 첫 번째로 추천되었습니다."
        if weather_matched
        else "비가 오면 실내, 맑으면 야외, 그 밖의 날씨에는 날씨 영향을 적게 받는 장소를 먼저 추천해야 합니다."
    )
    return {"passed": weather_matched, "score": score, "feedback": feedback, "failed_criteria": failed}


def evaluate_hotel_recommendation(hotels: list[dict[str, object]]) -> dict[str, object]:
    """숙소 후보가 장소 주변성과 가격 정보를 포함하는지 평가합니다."""

    if not hotels:
        return {"passed": False, "score": 0, "feedback": "숙소 후보가 없습니다.", "failed_criteria": ["hotel_exists"]}

    has_distance = all("distance_minutes" in hotel for hotel in hotels)
    has_price = all("nightly_price" in hotel for hotel in hotels)
    score = 50 * int(has_distance) + 50 * int(has_price)
    failed = []
    if not has_distance:
        failed.append("distance")
    if not has_price:
        failed.append("price")
    feedback = "숙소 후보에 거리와 가격 정보가 포함되어 있습니다." if score == 100 else "숙소 후보에는 거리와 가격 정보가 모두 필요합니다."
    return {"passed": score == 100, "score": score, "feedback": feedback, "failed_criteria": failed}


def find_selected_hotel(hotels: list[dict[str, object]], hotel_id: str) -> dict[str, object] | None:
    """Redis Snapshot에 저장된 숙소 후보 중 사용자가 선택한 숙소를 찾습니다."""

    for hotel in hotels:
        if hotel.get("hotel_id") == hotel_id:
            return hotel
    return None


def find_selected_place(places: list[dict[str, object]], place_id: str) -> dict[str, object] | None:
    """Redis Snapshot의 장소 후보 중 사용자가 선택한 장소를 찾습니다."""

    for place in places:
        if place.get("place_id") == place_id:
            return place
    return None


def build_travel_booking_plan(
    request: TravelBookingStartRequest,
    run_id: str | None = None,
) -> dict[str, object]:
    """09의 첫 단계로 날씨에 맞는 장소 후보만 만듭니다."""

    run_id = run_id or str(uuid4())
    effective_weather = request.weather
    places = recommend_places(request.destination, effective_weather, request.preferences)
    place_evaluation = evaluate_place_recommendation(places, effective_weather)
    trace = [
        make_event(1, "request", "travel_supervisor", "completed", "여행 요청을 받았습니다.", {"destination": request.destination}),
        make_event(2, "weather_reference", "weather_mcp_server", "completed", "조회한 실제 날씨를 참고했습니다.", {"source": request.actual_weather.get("source", "not_requested"), "weather_label": request.actual_weather.get("weather_label")}),
        make_event(3, "place_search", "weather_place_agent", "completed", "실제 날씨에 맞는 장소 후보를 만들었습니다.", {"weather": effective_weather, "count": len(places)}),
        make_event(4, "place_evaluation", "python_quality_gate", "passed" if place_evaluation["passed"] else "failed", place_evaluation["feedback"], place_evaluation),
        make_event(5, "wait_place_selection", "travel_supervisor", "waiting", "장소를 하나 선택하면 주변 숙소를 검색합니다."),
    ]
    return {
        "run_id": run_id,
        "status": "waiting_for_place_selection",
        "progress": 35,
        "user_id": request.user_id,
        "destination": request.destination,
        "weather": effective_weather,
        "actual_weather": request.actual_weather,
        "preferences": request.preferences,
        "place_options": places,
        "place_evaluation": place_evaluation,
        "events": trace,
    }


def create_travel_booking_plan(request: TravelBookingStartRequest) -> dict[str, object]:
    """1단계 API에서 호출합니다. 추천 결과를 만들고 Redis에도 현재 상태를 남깁니다."""

    state = build_travel_booking_plan(request)
    run_id = str(state["run_id"])
    save_snapshot(run_id, {key: value for key, value in state.items() if key != "events"})
    for event in state["events"]:
        append_event(run_id, event)
    return state


def search_hotels_for_selected_place(
    request: TravelPlaceSelectRequest,
    hotel_searcher: HotelSearcher = search_hotels_for_places,
) -> dict[str, object]:
    """사용자가 선택한 장소 하나만 Hotel MCP 서버로 보내 숙소를 검색합니다."""

    state = load_snapshot(request.run_id)
    if state is None:
        raise ValueError("run_id에 해당하는 장소 추천 실행을 찾을 수 없습니다.")
    if state.get("user_id") != request.user_id:
        raise ValueError("추천을 만든 사용자 ID와 장소 선택 사용자 ID가 다릅니다.")
    if state.get("status") not in {"waiting_for_place_selection", "waiting_for_hotel_selection", "hotel_search_failed"}:
        raise ValueError("숙소 선택을 끝내기 전 단계에서만 장소를 다시 선택할 수 있습니다.")

    place = find_selected_place(state.get("place_options", []), request.place_id)
    if place is None:
        raise ValueError("선택한 place_id를 현재 추천 결과에서 찾을 수 없습니다.")

    next_sequence = len(load_events(request.run_id)) + 1
    append_event(request.run_id, make_event(next_sequence, "place_selected", "user", "completed", "사용자가 장소를 선택했습니다.", {"place_id": request.place_id}))
    try:
        hotels = hotel_searcher([place])
        search_status = "completed"
        search_message = "선택한 장소 주변 숙소를 Hotel MCP 서버에서 조회했습니다."
    except Exception:
        hotels = []
        search_status = "failed"
        search_message = "Hotel MCP 서버 호출에 실패했습니다. 서버 실행 상태를 확인하세요."

    hotel_evaluation = evaluate_hotel_recommendation(hotels)
    append_event(request.run_id, make_event(next_sequence + 1, "hotel_mcp_search", "hotel_mcp_server", search_status, search_message, {"count": len(hotels)}))
    append_event(request.run_id, make_event(next_sequence + 2, "hotel_evaluation", "python_quality_gate", "passed" if hotel_evaluation["passed"] else "failed", hotel_evaluation["feedback"], hotel_evaluation))
    append_event(request.run_id, make_event(next_sequence + 3, "wait_hotel_selection", "travel_supervisor", "waiting" if hotels else "blocked", "숙소, 날짜, 인원을 확인한 뒤 승인해 주세요." if hotels else "예약 가능한 숙소가 없습니다."))

    state.update({
        "status": "waiting_for_hotel_selection" if hotels else "hotel_search_failed",
        "progress": 70 if hotels else 100,
        "selected_place": place,
        "hotel_options": hotels,
        "hotel_evaluation": hotel_evaluation,
    })
    save_snapshot(request.run_id, state)
    return {**state, "events": load_events(request.run_id)}


async def approve_travel_plan(request: TravelPlanApprovalRequest) -> dict[str, object]:
    """1차 승인 후 예상 예산과 여행 가이드를 만들고 실제 예약 전에서 멈춥니다."""

    state = load_snapshot(request.run_id)
    if state is None:
        raise ValueError("run_id에 해당하는 여행 실행을 찾을 수 없습니다.")
    if state.get("user_id") != request.user_id:
        raise ValueError("여행 실행을 만든 사용자 ID와 승인 사용자 ID가 다릅니다.")
    if state.get("status") == "waiting_for_booking_approval":
        return {**state, "events": load_events(request.run_id)}
    if state.get("status") not in {"waiting_for_hotel_selection", "plan_failed"}:
        raise ValueError("현재 단계에서는 여행 계획 생성을 승인할 수 없습니다.")

    hotel = find_selected_hotel(state.get("hotel_options", []), request.hotel_id)
    if hotel is None:
        raise ValueError("선택한 hotel_id를 현재 숙소 후보에서 찾을 수 없습니다.")
    place = state.get("selected_place")
    if not isinstance(place, dict):
        raise ValueError("먼저 장소를 선택해야 합니다.")

    nights = (request.check_out - request.check_in).days
    budget = calculate_trip_budget(hotel, nights, request.guest_count)
    guide_result, guide_metadata, guide_evaluations = await create_evaluated_travel_guide(
        place,
        hotel,
        budget,
        nights,
        str(state.get("weather", "날씨 정보 없음")),
    )
    guide = guide_result.model_dump()
    plan_approved_at = datetime.now(timezone.utc).isoformat()
    approved_plan = {
        "hotel_id": request.hotel_id,
        "hotel_name": hotel["name"],
        "check_in": request.check_in.isoformat(),
        "check_out": request.check_out.isoformat(),
        "guest_count": request.guest_count,
        "nights": nights,
    }
    next_sequence = len(load_events(request.run_id)) + 1
    append_event(request.run_id, make_event(next_sequence, "plan_approved", "user", "completed", "사용자가 선택한 숙소·일정·인원으로 여행 계획 생성을 승인했습니다.", {"hotel_id": request.hotel_id}))
    append_event(request.run_id, make_event(next_sequence + 1, "budget_calculated", "budget_agent", "completed", "항목별 예상 예산과 전체 금액을 계산했습니다.", {"total": budget["total"]}))
    append_event(request.run_id, make_event(next_sequence + 2, "guide_created", "openai_guide_writer", "completed", "OpenAI가 날씨·장소·숙소·예산을 반영한 여행 가이드를 만들었습니다.", guide_metadata))
    for offset, evaluation in enumerate(guide_evaluations, start=3):
        actor = "python_guide_quality_gate"
        append_event(request.run_id, make_event(next_sequence + offset, "guide_evaluation", actor, "passed" if evaluation["passed"] else "failed", evaluation["feedback"], evaluation))
    wait_sequence = next_sequence + 3 + len(guide_evaluations)
    if not guide_evaluations[-1]["passed"]:
        append_event(request.run_id, make_event(wait_sequence, "plan_blocked", "travel_supervisor", "blocked", "수정 후에도 여행 가이드가 품질 기준을 통과하지 못해 예약 승인을 열지 않습니다."))
        state.update({
            "status": "plan_failed",
            "progress": 100,
            "budget": budget,
            "travel_guide": guide,
            "guide_evaluations": guide_evaluations,
            "guide_provider": guide_metadata,
        })
        save_snapshot(request.run_id, state)
        return {**state, "events": load_events(request.run_id)}
    append_event(request.run_id, make_event(wait_sequence, "wait_booking_approval", "travel_supervisor", "waiting", "전체 예산과 여행 가이드를 확인한 뒤 실제 예약을 승인해 주세요."))
    state.update({
        "status": "waiting_for_booking_approval",
        "progress": 85,
        "approved_plan": approved_plan,
        "budget": budget,
        "travel_guide": guide,
        "guide_evaluations": guide_evaluations,
        "guide_provider": guide_metadata,
        "plan_approved_at": plan_approved_at,
    })
    save_snapshot(request.run_id, state)
    return {**state, "events": load_events(request.run_id)}


def confirm_travel_booking(request: TravelBookingConfirmRequest) -> dict[str, object]:
    """2차 승인 후 1차 승인 때 고정한 실행 인자로 Booking MCP를 호출합니다."""

    state = load_snapshot(request.run_id)
    if state is None:
        raise ValueError("run_id에 해당하는 추천 실행을 찾을 수 없습니다.")
    if state.get("user_id") != request.user_id:
        raise ValueError("추천을 만든 사용자 ID와 예약 사용자 ID가 다릅니다.")
    if state.get("status") == "booked":
        return {"status": "booked", "run_id": request.run_id, "booking": state["booking"], "events": load_events(request.run_id)}
    if state.get("status") not in {"waiting_for_booking_approval", "booking_failed"}:
        raise ValueError("먼저 여행 계획과 예산을 생성하고 2차 승인을 기다려야 합니다.")

    approved_plan = state.get("approved_plan")
    if not isinstance(approved_plan, dict):
        raise ValueError("1차 승인된 여행 계획을 찾을 수 없습니다.")
    hotel = find_selected_hotel(state.get("hotel_options", []), str(approved_plan["hotel_id"]))
    if hotel is None:
        raise ValueError("1차 승인된 숙소를 현재 후보에서 찾을 수 없습니다.")
    booking_approved_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "run_id": request.run_id,
        "user_id": request.user_id,
        "destination": state.get("destination"),
        "selected_place": state.get("selected_place", {}).get("name", hotel["near_place"]),
        "hotel_id": approved_plan["hotel_id"],
        "hotel_name": hotel["name"],
        "check_in": approved_plan["check_in"],
        "check_out": approved_plan["check_out"],
        "guest_count": approved_plan["guest_count"],
        "total_budget": state.get("budget", {}).get("total", 0),
        "travel_guide": state.get("travel_guide", {}),
        "plan_approved_at": state.get("plan_approved_at"),
        "booking_approved_at": booking_approved_at,
    }
    recovering = state.get("status") == "booking_failed"
    next_sequence = len(load_events(request.run_id)) + 1
    approval_stage = "booking_recovery_approved" if recovering else "booking_approved"
    approval_message = "사용자가 실패한 예약 단계만 다시 실행했습니다." if recovering else "사용자가 전체 예산과 여행 가이드를 확인하고 실제 예약을 승인했습니다."
    append_event(request.run_id, make_event(next_sequence, approval_stage, "user", "completed", approval_message, {"hotel_id": approved_plan["hotel_id"]}))

    booking = None
    last_error: Exception | None = None
    max_attempts = 2
    attempts_used = 0
    event_sequence = next_sequence + 1
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        append_event(
            request.run_id,
            make_event(event_sequence, "booking_request", "travel_supervisor", "started", f"Booking MCP 예약을 실행합니다. ({attempt}/{max_attempts})", {"hotel_id": approved_plan["hotel_id"], "attempt": attempt}),
        )
        event_sequence += 1
        try:
            if request.failure_scenario == "fail_once" and attempt == 1:
                raise TimeoutError("수업용 첫 예약 호출 Timeout")
            if request.failure_scenario == "fail_twice":
                raise TimeoutError(f"수업용 예약 호출 Timeout {attempt}")
            booking = book_accommodation(payload)
            append_event(
                request.run_id,
                make_event(event_sequence, "booking_mcp", "booking_mcp_server", "completed", "예약 MCP 서버가 예약을 처리하고 DB에 저장했습니다.", {"booking_id": booking["booking_id"], "attempt": attempt}),
            )
            event_sequence += 1
            break
        except Exception as error:
            last_error = error
            retryable = classify_failure(error) == "retry"
            will_retry = retryable and attempt < max_attempts
            append_event(
                request.run_id,
                make_event(
                    event_sequence,
                    "booking_mcp",
                    "booking_mcp_server",
                    "retrying" if will_retry else "failed",
                    "일시적 예약 오류입니다. 같은 예약 정보로 Booking MCP만 다시 실행합니다." if will_retry else booking_failure_message(error),
                    {"error_type": type(error).__name__, "attempt": attempt, "max_attempts": max_attempts, "failure_policy": "retry" if retryable else "stop"},
                ),
            )
            event_sequence += 1
            if not will_retry:
                break

    if booking is None:
        failure_message = booking_failure_message(last_error or RuntimeError("예약 결과 없음"))
        state.update({
            "status": "booking_failed",
            "progress": 100,
            "booking_error": failure_message,
            "booking_attempts": attempts_used,
            "preserved_results": ["selected_place", "approved_plan", "budget", "travel_guide", "plan_approved_at"],
            "retry_target": "booking_mcp",
        })
        save_snapshot(request.run_id, state)
        return {**state, "events": load_events(request.run_id)}

    state.update({"status": "booked", "progress": 100, "booking": booking})
    save_snapshot(request.run_id, state)
    return {"status": "booked", "run_id": request.run_id, "booking": booking, "events": load_events(request.run_id)}


async def run_booking_recovery_demo(request: BookingRecoveryDemoRequest) -> dict[str, object]:
    """11의 전체 예약과 선택한 장애를 한 번에 실행합니다.

    11은 복구에 집중하므로 장소와 숙소는 추천 점수가 가장 높은 후보를 자동 선택하고,
    사용자가 동의한 수업용 1차·2차 승인을 Trace에 명시적으로 남깁니다.
    """

    # MCP 클라이언트는 내부에서 동기 방식으로 세션을 실행합니다. FastAPI의 이벤트 루프와
    # 충돌하지 않도록 MCP가 포함된 동기 단계를 작업 스레드에서 실행합니다.
    actual_weather = await asyncio.to_thread(get_current_weather, request.destination)
    weather_label = str(actual_weather.get("weather_label", actual_weather.get("weather", "맑음")))
    plan = await asyncio.to_thread(
        create_travel_booking_plan,
        TravelBookingStartRequest(
            user_id=request.user_id,
            destination=request.destination,
            weather=weather_label,
            actual_weather=actual_weather,
            preferences=["실내", "맛집"],
        )
    )
    if not plan.get("place_options"):
        raise ValueError("자동 선택할 장소 후보가 없습니다.")

    selected_place = plan["place_options"][0]
    hotel_state = await asyncio.to_thread(
        search_hotels_for_selected_place,
        TravelPlaceSelectRequest(
            run_id=str(plan["run_id"]),
            user_id=request.user_id,
            place_id=str(selected_place["place_id"]),
        )
    )
    hotels = hotel_state.get("hotel_options", [])
    if not hotels:
        raise ValueError("자동 선택할 숙소 후보가 없습니다.")

    selected_hotel = hotels[0]
    check_in = date.today() + timedelta(days=7)
    check_out = check_in + timedelta(days=2)
    prepared = await approve_travel_plan(
        TravelPlanApprovalRequest(
            run_id=str(plan["run_id"]),
            user_id=request.user_id,
            hotel_id=str(selected_hotel["hotel_id"]),
            check_in=check_in,
            check_out=check_out,
            guest_count=2,
            approved=True,
        )
    )
    if prepared.get("status") != "waiting_for_booking_approval":
        return prepared

    return await asyncio.to_thread(
        confirm_travel_booking,
        TravelBookingConfirmRequest(
            run_id=str(plan["run_id"]),
            user_id=request.user_id,
            approved=True,
            failure_scenario=request.failure_scenario,
        )
    )

