"""Mini 07 실행 전 OpenAI·Gemma·Redis·PostgreSQL 연결을 확인합니다."""

import asyncio
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database.repository import list_criteria
from app.core.config import settings
from app.providers.registry import status
from app.storage.redis_store import client


CHECK_RESULTS: list[bool] = []


def check(name: str, success: bool, detail: str) -> None:
    CHECK_RESULTS.append(success)
    print(f"{'OK' if success else 'FAIL':<4} {name:<12} {detail}")


async def main() -> int:
    CHECK_RESULTS.clear()
    for provider in ("openai", "gemma"):
        provider_status = await status(provider)
        ready = bool(provider_status["configured"])
        if provider == "gemma":
            ready = ready and bool(provider_status.get("reachable")) and bool(provider_status.get("model_installed"))
        check(provider, ready, str(provider_status))

    try:
        with client() as redis:
            check("Redis", bool(redis.ping()), "connected")
    except Exception as error:
        check("Redis", False, str(error))

    try:
        criteria_count = len(list_criteria())
        check("PostgreSQL", criteria_count > 0, f"criteria={criteria_count}")
    except Exception as error:
        check("PostgreSQL", False, str(error))
    try:
        response = httpx.get(f"{settings.api_base_url}/health", timeout=5)
        response.raise_for_status()
        payload = response.json()
        expected = "mini_multi_agent_07_evaluation_feedback"
        actual = payload.get("project")
        check("Backend", payload.get("status") == "ok" and actual == expected, f"project={actual or 'unknown'} expected={expected}")
    except Exception as error:
        check("Backend", False, str(error))
    return 0 if all(CHECK_RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
