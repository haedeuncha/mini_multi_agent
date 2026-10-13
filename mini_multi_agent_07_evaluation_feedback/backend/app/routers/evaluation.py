from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agents.registry import registry_view
from app.database import repository
from app.orchestration.engine import new_run, run_feedback_workflow
from app.orchestration.failure_policy import classify_failure
from app.orchestration.support_flow import run_support_evaluation
from app.orchestration.travel_booking_flow import approve_travel_plan, confirm_travel_booking, create_travel_booking_plan, run_booking_recovery_demo, search_hotels_for_selected_place
from app.providers.registry import PROVIDERS, status
from app.providers.registry import ProviderExecutionError
from app.schemas.contracts import EvaluationRunRequest
from app.schemas.contracts import SupportEvaluationRequest
from app.schemas.contracts import TravelBookingConfirmRequest
from app.schemas.contracts import TravelBookingStartRequest
from app.schemas.contracts import TravelPlaceSelectRequest
from app.schemas.contracts import TravelPlanApprovalRequest
from app.schemas.contracts import BookingRecoveryDemoRequest
from app.storage.redis_store import load_events, load_snapshot, save_snapshot
from app.services.catalog import LABS
from app.services.weather_mcp_client import get_current_weather


router = APIRouter(prefix="/api")


@router.get("/labs")
def labs() -> dict[str, object]:
    return LABS


@router.get("/registry")
def registry() -> dict[str, object]:
    return registry_view()


@router.get("/criteria")
def criteria() -> list[dict[str, object]]:
    try:
        return repository.list_criteria()
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"PostgreSQL 평가 기준 조회 실패: {error}") from error


@router.get("/failure-cases")
def failure_cases() -> list[dict[str, str]]:
    examples = [
        TimeoutError("Provider 응답 지연"),
        ValueError("평가 기준 누락"),
        PermissionError("허용되지 않은 작업"),
        RuntimeError("자동 복구 불가"),
    ]
    return [{"error": type(error).__name__, "example": str(error), "decision": classify_failure(error)} for error in examples]


@router.get("/partial-recovery")
def partial_recovery() -> dict[str, object]:
    results = {
        "writer_agent": "completed",
        "evaluator_agent": "failed",
        "reference_loader": "completed",
    }
    return {
        "results": results,
        "kept_results": [name for name, result in results.items() if result == "completed"],
        "retry_target": "evaluator_agent",
        "principle": "성공 결과를 보존하고 실패한 부분만 복구합니다.",
    }


@router.get("/providers")
async def providers() -> dict[str, object]:
    return {provider: await status(provider) for provider in PROVIDERS}


@router.post("/runs", status_code=202)
async def create_evaluation_run(request: EvaluationRunRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    run_id, state = new_run(request)
    save_snapshot(run_id, state)
    background_tasks.add_task(run_feedback_workflow, run_id, state, request)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs/{run_id}")
def run_state(run_id: str) -> dict[str, object]:
    state = load_snapshot(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다.")
    return {**state, "events": load_events(run_id)}


@router.get("/history")
def history() -> list[dict[str, object]]:
    try:
        return repository.recent_runs()
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"PostgreSQL 실행 이력 조회 실패: {error}") from error


@router.get("/history/{run_id}/rounds")
def history_rounds(run_id: str) -> list[dict[str, object]]:
    try:
        return repository.run_rounds(run_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"PostgreSQL 평가 회차 조회 실패: {error}") from error


@router.post("/runs/support-evaluation")
async def support_evaluation(request: SupportEvaluationRequest) -> dict[str, object]:
    try:
        return await run_support_evaluation(request)
    except ProviderExecutionError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/travel-booking/plan")
def travel_booking_plan(request: TravelBookingStartRequest) -> dict[str, object]:
    try:
        if not request.actual_weather:
            actual_weather = get_current_weather(request.destination)
            weather_label = str(actual_weather.get("weather_label", actual_weather.get("weather", "맑음")))
            request = request.model_copy(update={"weather": weather_label, "actual_weather": actual_weather})
        return create_travel_booking_plan(request)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"여행 추천 실행 실패: {error}") from error


@router.post("/travel-booking/book")
def travel_booking_book(request: TravelBookingConfirmRequest) -> dict[str, object]:
    try:
        return confirm_travel_booking(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"숙소 예약 실행 실패: {error}") from error


@router.post("/travel-booking/recovery-demo")
async def travel_booking_recovery_demo(request: BookingRecoveryDemoRequest) -> dict[str, object]:
    try:
        return await run_booking_recovery_demo(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"예약 복구 실습 실행 실패: {error}") from error


@router.post("/travel-booking/prepare")
async def travel_booking_prepare(request: TravelPlanApprovalRequest) -> dict[str, object]:
    try:
        return await approve_travel_plan(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"여행 계획 생성 실패: {error}") from error


@router.post("/travel-booking/hotels")
def travel_booking_hotels(request: TravelPlaceSelectRequest) -> dict[str, object]:
    try:
        return search_hotels_for_selected_place(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"숙소 검색 실행 실패: {error}") from error


@router.get("/travel-booking/{run_id}")
def travel_booking_state(run_id: str) -> dict[str, object]:
    state = load_snapshot(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="여행 예약 실행을 찾을 수 없습니다.")
    return {**state, "events": load_events(run_id)}


@router.get("/weather/current")
def weather_current(destination: str = "부산") -> dict[str, object]:
    try:
        return get_current_weather(destination)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Weather MCP 역할 서버 조회 실패: {error}") from error


@router.get("/bookings")
def bookings(user_id: str | None = None) -> list[dict[str, object]]:
    try:
        return repository.list_booking_records(user_id=user_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"예약 이력 조회 실패: {error}") from error
