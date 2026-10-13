import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.orchestration.travel_booking_flow import (  # noqa: E402
    approve_travel_plan,
    build_travel_booking_plan,
    calculate_trip_budget,
    booking_failure_message,
    confirm_travel_booking,
    evaluate_hotel_recommendation,
    evaluate_place_recommendation,
    run_booking_recovery_demo,
    search_hotels_for_selected_place,
)
from app.schemas.contracts import BookingRecoveryDemoRequest, TravelBookingConfirmRequest, TravelBookingStartRequest, TravelGuideResult, TravelPlaceSelectRequest, TravelPlanApprovalRequest  # noqa: E402
from app.routers.evaluation import travel_booking_plan  # noqa: E402


def fake_hotel_searcher(places: list[dict[str, object]]) -> list[dict[str, object]]:
    first_place = places[0]
    return [
        {
            "hotel_id": "hotel-test",
            "place_id": first_place["place_id"],
            "name": "테스트 호텔",
            "near_place": first_place["name"],
            "nightly_price": 90000,
            "distance_minutes": 7,
            "recommendation_score": 90,
        }
    ]


class TravelBookingFlowTests(unittest.TestCase):
    @staticmethod
    def booking_ready_state() -> dict[str, object]:
        return {
            "user_id": "user-101",
            "status": "waiting_for_booking_approval",
            "destination": "부산",
            "selected_place": {"name": "부산시립미술관"},
            "hotel_options": [{"hotel_id": "hotel-artstay", "name": "아트스테이", "near_place": "부산시립미술관"}],
            "approved_plan": {"hotel_id": "hotel-artstay", "check_in": "2026-10-10", "check_out": "2026-10-12", "guest_count": 2},
            "budget": {"total": 430000},
            "travel_guide": {"title": "부산 여행"},
            "plan_approved_at": "2026-10-05T00:00:00+00:00",
        }

    @patch("app.routers.evaluation.create_travel_booking_plan")
    @patch("app.routers.evaluation.get_current_weather")
    def test_start_automatically_fetches_weather(self, get_current_weather, create_plan) -> None:
        get_current_weather.return_value = {
            "destination": "부산",
            "weather_label": "비",
            "temperature_c": 18,
        }
        create_plan.side_effect = lambda request: request.model_dump()

        result = travel_booking_plan(TravelBookingStartRequest(user_id="user-101", destination="부산"))

        get_current_weather.assert_called_once_with("부산")
        self.assertEqual(result["weather"], "비")
        self.assertEqual(result["actual_weather"]["temperature_c"], 18)

    def test_rainy_weather_prefers_indoor_place(self) -> None:
        request = TravelBookingStartRequest(destination="부산", weather="비", preferences=["실내"])
        result = build_travel_booking_plan(
            request,
            run_id="00000000-0000-0000-0000-000000000001",
        )

        self.assertEqual(result["status"], "waiting_for_place_selection")
        self.assertEqual(result["place_options"][0]["weather_fit"], "rainy")
        self.assertTrue(result["place_evaluation"]["passed"])

    def test_sunny_weather_prefers_outdoor_or_all_weather_place(self) -> None:
        evaluation = evaluate_place_recommendation(
            [{"name": "광안리 해변", "weather_fit": "sunny"}],
            weather="맑음",
        )

        self.assertTrue(evaluation["passed"])
        self.assertEqual(evaluation["score"], 100)

    def test_sunny_weather_does_not_pass_rain_only_place(self) -> None:
        evaluation = evaluate_place_recommendation(
            [{"name": "실내 전시장", "weather_fit": "rainy"}],
            weather="맑음",
        )

        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["score"], 60)

    def test_place_evaluation_fails_when_no_place_exists(self) -> None:
        evaluation = evaluate_place_recommendation([], weather="비")

        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["score"], 0)
        self.assertIn("place_exists", evaluation["failed_criteria"])

    def test_hotel_evaluation_requires_price_and_distance(self) -> None:
        evaluation = evaluate_hotel_recommendation([{"name": "숙소"}])

        self.assertFalse(evaluation["passed"])
        self.assertEqual(evaluation["score"], 0)
        self.assertEqual(evaluation["failed_criteria"], ["distance", "price"])

    def test_budget_contains_lodging_and_per_person_costs(self) -> None:
        budget = calculate_trip_budget({"nightly_price": 90000}, nights=2, guest_count=2)
        self.assertEqual(budget["lodging"], 180000)
        self.assertEqual(budget["food"], 180000)
        self.assertEqual(budget["total"], 430000)

    def test_booking_failure_explains_common_recovery_action(self) -> None:
        self.assertIn("Booking MCP", booking_failure_message(ConnectionError("connection refused")))
        self.assertIn("다시 실행", booking_failure_message(RuntimeError("arguments validation error")))
        self.assertIn("apply_schema.py", booking_failure_message(RuntimeError('column "total_budget" does not exist')))

    def test_plan_trace_has_unique_ordered_steps(self) -> None:
        result = build_travel_booking_plan(
            TravelBookingStartRequest(),
        )
        self.assertEqual([event["sequence"] for event in result["events"]], list(range(1, 6)))
        self.assertNotIn("user_id", result["events"][0]["details"])

    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_hotel_search_uses_only_selected_place(self, load_snapshot, load_events, append_event, save_snapshot) -> None:
        places = build_travel_booking_plan(TravelBookingStartRequest())["place_options"]
        load_snapshot.return_value = {"run_id": "run-1", "user_id": "user-101", "status": "waiting_for_place_selection", "place_options": places}
        request = TravelPlaceSelectRequest(run_id="run-1", place_id=places[0]["place_id"])
        result = search_hotels_for_selected_place(request, hotel_searcher=fake_hotel_searcher)
        self.assertEqual(result["status"], "waiting_for_hotel_selection")
        self.assertEqual(result["selected_place"]["place_id"], places[0]["place_id"])
        self.assertEqual(result["hotel_options"][0]["hotel_id"], "hotel-test")

    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_place_can_be_changed_before_hotel_approval(self, load_snapshot, load_events, append_event, save_snapshot) -> None:
        places = build_travel_booking_plan(TravelBookingStartRequest())["place_options"]
        load_snapshot.return_value = {
            "run_id": "run-1",
            "user_id": "user-101",
            "status": "waiting_for_hotel_selection",
            "place_options": places,
        }

        result = search_hotels_for_selected_place(
            TravelPlaceSelectRequest(run_id="run-1", place_id=places[-1]["place_id"]),
            hotel_searcher=fake_hotel_searcher,
        )

        self.assertEqual(result["status"], "waiting_for_hotel_selection")
        self.assertEqual(result["selected_place"]["place_id"], places[-1]["place_id"])

    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_booking_rejects_different_user(self, load_snapshot) -> None:
        load_snapshot.return_value = {"user_id": "user-101", "status": "waiting_for_booking_approval"}
        request = TravelBookingConfirmRequest(run_id="run-1", user_id="user-999", approved=True)
        with self.assertRaisesRegex(ValueError, "사용자 ID"):
            confirm_travel_booking(request)

    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_booking_reuses_completed_result(self, load_snapshot, load_events) -> None:
        load_snapshot.return_value = {"user_id": "user-101", "status": "booked", "booking": {"booking_id": "booking-1"}}
        request = TravelBookingConfirmRequest(run_id="run-1", approved=True)
        result = confirm_travel_booking(request)
        self.assertEqual(result["booking"]["booking_id"], "booking-1")

    @patch("app.orchestration.travel_booking_flow.book_accommodation", return_value={"booking_id": "booking-1", "status": "confirmed"})
    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_approved_booking_calls_booking_server(self, load_snapshot, load_events, append_event, save_snapshot, book_accommodation) -> None:
        state = self.booking_ready_state()
        load_snapshot.return_value = state
        request = TravelBookingConfirmRequest(run_id="run-1", approved=True)
        result = confirm_travel_booking(request)
        self.assertEqual(result["status"], "booked")
        self.assertEqual(state["status"], "booked")
        self.assertEqual(book_accommodation.call_args.args[0]["selected_place"], "부산시립미술관")
        self.assertEqual(book_accommodation.call_args.args[0]["total_budget"], 430000)
        self.assertEqual(append_event.call_args_list[0].args[1]["stage"], "booking_approved")
        save_snapshot.assert_called_once()

    @patch("app.orchestration.travel_booking_flow.book_accommodation", return_value={"booking_id": "booking-1", "status": "confirmed"})
    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_first_booking_failure_retries_only_booking_step(self, load_snapshot, load_events, append_event, save_snapshot, book_accommodation) -> None:
        load_snapshot.return_value = self.booking_ready_state()

        result = confirm_travel_booking(TravelBookingConfirmRequest(run_id="run-1", approved=True, failure_scenario="fail_once"))

        self.assertEqual(result["status"], "booked")
        book_accommodation.assert_called_once()
        statuses = [call.args[1]["status"] for call in append_event.call_args_list]
        self.assertIn("retrying", statuses)

    @patch("app.orchestration.travel_booking_flow.book_accommodation")
    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    def test_two_booking_failures_preserve_plan_for_manual_recovery(self, load_snapshot, load_events, append_event, save_snapshot, book_accommodation) -> None:
        load_snapshot.return_value = self.booking_ready_state()

        result = confirm_travel_booking(TravelBookingConfirmRequest(run_id="run-1", approved=True, failure_scenario="fail_twice"))

        self.assertEqual(result["status"], "booking_failed")
        self.assertEqual(result["retry_target"], "booking_mcp")
        self.assertIn("budget", result["preserved_results"])
        book_accommodation.assert_not_called()

    @patch("app.orchestration.travel_booking_flow.save_snapshot")
    @patch("app.orchestration.travel_booking_flow.append_event")
    @patch("app.orchestration.travel_booking_flow.load_events", return_value=[])
    @patch("app.orchestration.travel_booking_flow.load_snapshot")
    @patch("app.orchestration.travel_booking_flow.create_evaluated_travel_guide", new_callable=AsyncMock)
    def test_first_approval_creates_budget_and_guide_without_booking(self, create_guide, load_snapshot, load_events, append_event, save_snapshot) -> None:
        state = {
            "user_id": "user-101",
            "status": "waiting_for_hotel_selection",
            "weather": "비",
            "selected_place": {"name": "부산 현대 미술관", "destination": "부산", "summary": "실내 장소", "tags": ["실내", "전시"]},
            "hotel_options": [{"hotel_id": "hotel-test", "name": "테스트 호텔", "near_place": "부산 현대 미술관", "nightly_price": 90000}],
        }
        load_snapshot.return_value = state
        create_guide.return_value = (
            TravelGuideResult(
                title="부산 여행",
                weather_tip="비 오는 날 실내 장소를 이용합니다.",
                schedule=[
                    {"day": 1, "guide": "부산 현대 미술관 방문"},
                    {"day": 2, "guide": "테스트 호텔 주변 여행"},
                    {"day": 3, "guide": "최종 승인 후 예약"},
                ],
                notice="전체 예산은 예상 금액입니다.",
            ),
            {"provider": "openai", "model": "test-model"},
            [{"passed": True, "score": 100, "failed_criteria": [], "feedback": "통과"}],
        )
        request = TravelPlanApprovalRequest(run_id="run-1", hotel_id="hotel-test", check_in="2026-10-10", check_out="2026-10-12", guest_count=2, approved=True)
        result = asyncio.run(approve_travel_plan(request))
        self.assertEqual(result["status"], "waiting_for_booking_approval")
        self.assertEqual(result["budget"]["total"], 430000)
        self.assertIn("travel_guide", result)
        self.assertEqual(result["guide_provider"]["provider"], "openai")
        self.assertNotIn("booking", result)
        self.assertEqual(append_event.call_args_list[0].args[1]["stage"], "plan_approved")

    def test_checkout_must_be_after_checkin(self) -> None:
        with self.assertRaises(ValidationError):
            TravelPlanApprovalRequest(
                run_id="run-1", hotel_id="hotel-artstay",
                check_in="2026-10-10", check_out="2026-10-09",
                approved=True,
            )

    def test_both_approvals_are_required(self) -> None:
        with self.assertRaisesRegex(ValidationError, "계획과 예산 생성을 먼저 승인"):
            TravelPlanApprovalRequest(run_id="run-1", hotel_id="hotel-artstay", approved=False)
        with self.assertRaisesRegex(ValidationError, "실제 예약을 승인"):
            TravelBookingConfirmRequest(run_id="run-1", approved=False)
        with self.assertRaisesRegex(ValidationError, "자동 승인"):
            BookingRecoveryDemoRequest(auto_approve=False)

    @patch("app.orchestration.travel_booking_flow.confirm_travel_booking")
    @patch("app.orchestration.travel_booking_flow.approve_travel_plan", new_callable=AsyncMock)
    @patch("app.orchestration.travel_booking_flow.search_hotels_for_selected_place")
    @patch("app.orchestration.travel_booking_flow.create_travel_booking_plan")
    @patch("app.orchestration.travel_booking_flow.get_current_weather")
    def test_recovery_demo_runs_full_flow_from_one_request(self, weather, create_plan, search_hotels, approve_plan, confirm_booking) -> None:
        weather.return_value = {"weather_label": "비", "source": "test"}
        create_plan.return_value = {"run_id": "run-11", "place_options": [{"place_id": "place-1", "name": "실내 장소"}]}
        search_hotels.return_value = {"hotel_options": [{"hotel_id": "hotel-1", "name": "테스트 호텔"}]}
        approve_plan.return_value = {"status": "waiting_for_booking_approval"}
        confirm_booking.return_value = {"status": "booked", "run_id": "run-11"}

        result = asyncio.run(run_booking_recovery_demo(BookingRecoveryDemoRequest(auto_approve=True, failure_scenario="fail_once")))

        self.assertEqual(result["status"], "booked")
        self.assertEqual(confirm_booking.call_args.args[0].failure_scenario, "fail_once")
        approve_plan.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
