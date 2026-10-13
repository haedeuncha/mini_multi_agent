import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.orchestration.failure_policy import classify_failure  # noqa: E402
from app.orchestration.engine import execute_with_retry  # noqa: E402
from app.providers.registry import ProviderExecutionError, normalize_provider_error  # noqa: E402


class FailurePolicyTests(unittest.TestCase):
    def test_retryable_provider_error_is_retried(self) -> None:
        error = normalize_provider_error("gemma", TimeoutError("private timeout body"))
        self.assertEqual(classify_failure(error), "retry")
        self.assertNotIn("private timeout body", str(error))

    def test_quota_with_retry_after_is_normalized(self) -> None:
        error = normalize_provider_error("gemma", RuntimeError("429 RESOURCE_EXHAUSTED retryDelay: '30s' private"))
        self.assertEqual(error.code, "quota_exhausted")
        self.assertEqual(error.retry_after_seconds, 30)
        self.assertEqual(classify_failure(error), "retry")

    def test_temporary_server_error_is_retryable(self) -> None:
        error = normalize_provider_error("gemma", RuntimeError("503 UNAVAILABLE"))
        self.assertEqual(error.code, "provider_unavailable")
        self.assertTrue(error.retryable)

    def test_non_retryable_error_escalates(self) -> None:
        self.assertEqual(classify_failure(RuntimeError("broken")), "human_escalation")

    def test_yaml_error_names_control_retry(self) -> None:
        self.assertEqual(classify_failure(TimeoutError("slow"), {"ConnectionError"}), "human_escalation")
        self.assertEqual(classify_failure(TimeoutError("slow"), {"TimeoutError"}), "retry")


class RetryWaitTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.orchestration.engine.asyncio.sleep", new_callable=AsyncMock)
    async def test_provider_retry_waits_for_requested_delay(self, sleep: AsyncMock) -> None:
        error = ProviderExecutionError(
            "요청 제한", code="quota_exhausted", retryable=True, retry_after_seconds=3
        )
        operation = AsyncMock(side_effect=[error, ("ok", {})])
        result = await execute_with_retry(operation, (), "writer", "write", MagicMock())
        self.assertEqual(result, ("ok", {}))
        sleep.assert_awaited_once_with(3)


if __name__ == "__main__":
    unittest.main()
