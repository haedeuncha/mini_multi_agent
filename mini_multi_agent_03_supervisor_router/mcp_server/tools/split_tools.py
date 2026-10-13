"""[Workshop 3] Lab 10 · 공정 N빵 정산 Mock Tool.

PostgreSQL 대신 mock_data/split_gatherings.json을 읽는다. 조회 전용이며 값을 바꾸지 않는다.
Tool 결과에는 항상 source를 남겨 Trace에서 Mock 데이터임을 알 수 있게 한다.
"""

import json
from functools import lru_cache
from pathlib import Path

MOCK_FILE = Path(__file__).resolve().parents[1] / "mock_data" / "split_gatherings.json"
SOURCE = "mock:split_gatherings.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(MOCK_FILE.read_text(encoding="utf-8"))


def _gathering(gathering_id: str) -> dict | None:
    return _data()["gatherings"].get(gathering_id.strip().upper())


def get_receipt(gathering_id: str) -> dict:
    """모임의 차수별 영수증 원문 줄(raw_lines)과 인쇄된 합계를 조회합니다."""
    row = _gathering(gathering_id)
    if row is None:
        return {"success": False, "error": f"{gathering_id} 모임을 찾을 수 없습니다.", "source": SOURCE}
    return {"success": True, "gathering_id": gathering_id.upper(), "title": row["title"],
            "receipts": row["receipts"], "source": SOURCE}


def get_gathering_members(gathering_id: str) -> dict:
    """모임 멤버 이름 목록과 차수 ID를 조회합니다."""
    row = _gathering(gathering_id)
    if row is None:
        return {"success": False, "error": f"{gathering_id} 모임을 찾을 수 없습니다.", "source": SOURCE}
    rounds = [{"round_id": r["round_id"], "round_name": r["round_name"]} for r in row["receipts"]]
    return {"success": True, "members": row["members"], "rounds": rounds, "source": SOURCE}


def get_menu_categories() -> dict:
    """자주 나오는 메뉴의 기본 분류 사전(food / alcohol / equal)을 조회합니다."""
    return {"success": True, "categories": _data()["menu_categories"], "source": SOURCE}
