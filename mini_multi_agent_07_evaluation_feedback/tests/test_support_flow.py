import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.orchestration.support_flow import (  # noqa: E402
    evaluate_support_text,
    generate_with_retry,
    run_support_evaluation,
)
from app.providers.registry import ProviderExecutionError  # noqa: E402
from app.schemas.contracts import (  # noqa: E402
    EvaluationResult,
    SupportEvaluationRequest,
    WritingResult,
)


class SupportEvaluationFlowTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.orchestration.support_flow.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.orchestration.support_flow.generate", new_callable=AsyncMock)
    async def test_temporary_openai_failure_retries_once(self, generate: AsyncMock, sleep: AsyncMock) -> None:
        temporary_error = ProviderExecutionError("일시적 오류", code="provider_unavailable", retryable=True)
        expected = (EvaluationResult(passed=True, score=100, feedback="통과"), {"provider": "openai"})
        generate.side_effect = [temporary_error, expected]

        result = await generate_with_retry("openai", "평가", EvaluationResult)

        self.assertEqual(result, expected)
        self.assertEqual(generate.await_count, 2)
        sleep.assert_awaited_once_with(1)

    def test_python_gate_checks_required_text(self) -> None:
        draft = WritingResult(
            title="로그인 안내",
            content="확인 절차를 안내합니다.",
            included_requirements=[],
        )
        score, failed = evaluate_support_text(draft)
        self.assertEqual(score, 50)
        self.assertEqual(failed, ["no_false_claim"])

    @patch("app.orchestration.support_flow.generate", new_callable=AsyncMock)
    async def test_failed_draft_is_revised_and_re_evaluated(self, generate: AsyncMock) -> None:
        failed_draft = WritingResult(title="초안", content="확인 절차를 안내합니다.", included_requirements=[])
        passed_draft = WritingResult(title="수정안", content="확인 절차를 안내합니다. 실제 변경을 완료하지 않았습니다.", included_requirements=[])
        llm_evaluation = EvaluationResult(passed=False, score=50, feedback="미실행 고지를 추가하세요.")
        final_evaluation = EvaluationResult(passed=True, score=100, feedback="기준 충족")
        generate.side_effect = [
            (failed_draft, {"provider": "openai"}),
            (llm_evaluation, {"provider": "openai"}),
            (passed_draft, {"provider": "openai"}),
            (final_evaluation, {"provider": "openai"}),
        ]

        result = await run_support_evaluation(SupportEvaluationRequest())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["score"], 100)
        self.assertEqual(generate.await_count, 4)

    @patch("app.orchestration.support_flow.generate", new_callable=AsyncMock)
    async def test_complete_first_draft_stops_early(self, generate: AsyncMock) -> None:
        draft = WritingResult(title="초안", content="확인 절차입니다. 실제 변경을 완료하지 않았습니다.", included_requirements=[])
        evaluation = EvaluationResult(passed=True, score=100, feedback="기준 충족")
        generate.side_effect = [
            (draft, {"provider": "openai"}),
            (evaluation, {"provider": "openai"}),
        ]

        result = await run_support_evaluation(SupportEvaluationRequest(demonstrate_revision=False))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(generate.await_count, 2)

    @patch("app.orchestration.support_flow.generate", new_callable=AsyncMock)
    async def test_quality_failure_stops_after_four_evaluations(self, generate: AsyncMock) -> None:
        draft = WritingResult(title="초안", content="확인 절차만 안내합니다.", included_requirements=[])
        evaluation = EvaluationResult(passed=False, score=50, feedback="미실행 고지가 필요합니다.")
        generate.side_effect = [
            (draft, {"provider": "openai"}),
            (evaluation, {"provider": "openai"}),
            (draft, {"provider": "openai"}),
            (evaluation, {"provider": "openai"}),
            (draft, {"provider": "openai"}),
            (evaluation, {"provider": "openai"}),
            (draft, {"provider": "openai"}),
            (evaluation, {"provider": "openai"}),
        ]

        result = await run_support_evaluation(SupportEvaluationRequest())

        self.assertEqual(result["status"], "quality_failed")
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(generate.await_count, 8)


if __name__ == "__main__":
    unittest.main()
