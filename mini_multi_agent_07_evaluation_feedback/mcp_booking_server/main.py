r"""Booking MCP Server.

실행 명령:
    cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
    .\.venv\Scripts\Activate.ps1
    python .\mcp_booking_server\main.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent_user:agent_pwd@127.0.0.1:5433/agent_db")

mcp = FastMCP(
    "mini07-booking-tools",
    host="127.0.0.1",
    port=int(os.getenv("BOOKING_MCP_PORT", "18010")),
    stateless_http=True,
    json_response=True,
)

WRITE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)

READ_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)


@mcp.tool(annotations=WRITE_TOOL)
def book_accommodation(
    run_id: str,
    user_id: str,
    destination: str,
    selected_place: str,
    hotel_id: str,
    hotel_name: str,
    check_in: str,
    check_out: str,
    guest_count: int,
    total_budget: int,
    travel_guide: dict[str, object],
    plan_approved_at: str,
    booking_approved_at: str,
) -> dict[str, object]:
    """사용자가 승인한 숙소 예약을 처리하고 PostgreSQL에 저장합니다."""

    payload = {
        "run_id": run_id,
        "user_id": user_id,
        "destination": destination,
        "selected_place": selected_place,
        "hotel_id": hotel_id,
        "hotel_name": hotel_name,
        "check_in": check_in,
        "check_out": check_out,
        "guest_count": guest_count,
        "total_budget": total_budget,
        "travel_guide": travel_guide,
        "plan_approved_at": plan_approved_at,
        "booking_approved_at": booking_approved_at,
    }
    booking_id = str(uuid4())
    print("[Booking MCP] 예약 요청 수신", payload, flush=True)
    with connection() as database:
        existing = database.execute(
            """SELECT booking_id::text, status, booking_payload
               FROM mini_multi_agent_07.booking_records WHERE run_id=%s LIMIT 1""",
            (run_id,),
        ).fetchone()
        if existing:
            print("[Booking MCP] 같은 실행의 기존 예약 반환", existing["booking_id"], flush=True)
            return {"booking_id": existing["booking_id"], "status": existing["status"], **existing["booking_payload"]}
        database.execute(
            """INSERT INTO mini_multi_agent_07.booking_records
               (booking_id, run_id, user_id, destination, selected_place, hotel_id,
                hotel_name, check_in, check_out, guest_count, total_budget, travel_guide,
                plan_approved_at, booking_approved_at, status, booking_payload)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                       %s::timestamptz, %s::timestamptz, 'confirmed', %s::jsonb)""",
            (
                booking_id,
                run_id,
                user_id,
                destination,
                selected_place,
                hotel_id,
                hotel_name,
                check_in,
                check_out,
                guest_count,
                total_budget,
                json.dumps(travel_guide, ensure_ascii=False),
                plan_approved_at,
                booking_approved_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    result = {"booking_id": booking_id, "status": "confirmed", **payload}
    print("[Booking MCP] 예약 저장 완료", result, flush=True)
    return result


@mcp.tool(annotations=READ_TOOL)
def list_bookings(user_id: str | None = None) -> list[dict[str, object]]:
    """저장된 예약 이력을 조회합니다."""

    with connection() as database:
        if user_id:
            return database.execute(
                """SELECT booking_id::text, run_id::text, user_id, destination, selected_place,
                          hotel_id, hotel_name, check_in::text, check_out::text, guest_count,
                          total_budget, travel_guide, plan_approved_at, booking_approved_at,
                          status, created_at
                   FROM mini_multi_agent_07.booking_records
                   WHERE user_id=%s
                   ORDER BY created_at DESC""",
                (user_id,),
            ).fetchall()
        return database.execute(
            """SELECT booking_id::text, run_id::text, user_id, destination, selected_place,
                      hotel_id, hotel_name, check_in::text, check_out::text, guest_count,
                      total_budget, travel_guide, plan_approved_at, booking_approved_at,
                      status, created_at
               FROM mini_multi_agent_07.booking_records
               ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
