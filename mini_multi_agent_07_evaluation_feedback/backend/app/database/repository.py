import json

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


def connection():
    return psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5)


def list_criteria() -> list[dict[str, object]]:
    with connection() as database:
        return database.execute(
            """SELECT criterion_key, description, required_text, weight, mandatory
               FROM mini_multi_agent_07.evaluation_criteria
               WHERE active = TRUE ORDER BY criterion_key"""
        ).fetchall()


def create_run(run_id: str, user_id: str, request_text: str) -> None:
    with connection() as database:
        database.execute(
            """INSERT INTO mini_multi_agent_07.evaluation_runs
               (run_id, user_id, request_text, status) VALUES (%s, %s, %s, 'running')""",
            (run_id, user_id, request_text),
        )


def save_round(run_id: str, round_number: int, draft: str, evaluation: dict[str, object], metadata: dict[str, object]) -> None:
    with connection() as database:
        database.execute(
            """INSERT INTO mini_multi_agent_07.evaluation_rounds
               (run_id, round_number, draft_content, score, passed, feedback,
                failed_criteria, provider, model, latency_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)""",
            (
                run_id, round_number, draft, evaluation["score"], evaluation["passed"],
                evaluation["feedback"], json.dumps(evaluation["failed_criteria"], ensure_ascii=False),
                metadata["provider"], metadata["model"], metadata.get("latency_ms"),
            ),
        )


def complete_run(run_id: str, status: str, score: int | None, content: str | None, error: str | None = None) -> None:
    with connection() as database:
        database.execute(
            """UPDATE mini_multi_agent_07.evaluation_runs
               SET status=%s, final_score=%s, final_content=%s, error_message=%s, completed_at=NOW()
               WHERE run_id=%s""",
            (status, score, content, error, run_id),
        )


def recent_runs(limit: int = 20) -> list[dict[str, object]]:
    with connection() as database:
        return database.execute(
            """SELECT run_id::text, user_id, status, final_score, created_at, completed_at
               FROM mini_multi_agent_07.evaluation_runs
               ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        ).fetchall()


def run_rounds(run_id: str) -> list[dict[str, object]]:
    with connection() as database:
        return database.execute(
            """SELECT round_number, score, passed, feedback, failed_criteria,
                      provider, model, latency_ms, created_at
               FROM mini_multi_agent_07.evaluation_rounds
               WHERE run_id=%s ORDER BY round_number""",
            (run_id,),
        ).fetchall()


def list_booking_records(user_id: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    """숙소 예약 MCP 역할 서버가 저장한 예약 이력을 조회합니다."""

    with connection() as database:
        if user_id:
            return database.execute(
                """SELECT booking_id::text, run_id::text, user_id, destination, selected_place,
                          hotel_id, hotel_name, check_in::text, check_out::text, guest_count,
                          total_budget, travel_guide, plan_approved_at, booking_approved_at,
                          status, created_at
                   FROM mini_multi_agent_07.booking_records
                   WHERE user_id=%s
                   ORDER BY created_at DESC LIMIT %s""",
                (user_id, limit),
            ).fetchall()
        return database.execute(
            """SELECT booking_id::text, run_id::text, user_id, destination, selected_place,
                      hotel_id, hotel_name, check_in::text, check_out::text, guest_count,
                      total_budget, travel_guide, plan_approved_at, booking_approved_at,
                      status, created_at
               FROM mini_multi_agent_07.booking_records
               ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        ).fetchall()
