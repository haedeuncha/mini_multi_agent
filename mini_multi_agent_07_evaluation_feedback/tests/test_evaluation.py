import sys
import unittest
from pathlib import Path
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agents.evaluator_agent import deterministic_checks  # noqa: E402
from app.agents.registry import AGENTS, load_policies, provider_for_agent  # noqa: E402
from app.schemas.contracts import EvaluationRunRequest, WritingResult  # noqa: E402
from app.orchestration.engine import validate_criteria  # noqa: E402


class EvaluationTests(unittest.TestCase):
    def test_agent_provider_mapping(self) -> None:
        expected = {"writer_agent": "openai", "evaluator_agent": "gemma", "reviser_agent": "openai"}
        self.assertEqual({key: provider_for_agent(key) for key in expected}, expected)
        self.assertEqual({key: AGENTS[key].provider for key in expected}, expected)

    def test_policy_is_valid(self) -> None:
        self.assertEqual(load_policies()["quality_gate"]["minimum_score"], 80)

    def test_deterministic_score_uses_required_text(self) -> None:
        criteria = [
            {"criterion_key": "a", "required_text": "필수 A", "weight": 60, "mandatory": True},
            {"criterion_key": "b", "required_text": "필수 B", "weight": 40, "mandatory": False},
        ]
        passed, score = deterministic_checks(WritingResult(title="안내", content="필수 A를 포함합니다.", included_requirements=[]), criteria)
        self.assertEqual((passed, score), (["a"], 60))

    def test_score_is_capped_at_100(self) -> None:
        criteria = [{"criterion_key": "a", "required_text": "A", "weight": 120, "mandatory": True}]
        _, score = deterministic_checks(WritingResult(title="안내", content="A", included_requirements=[]), criteria)
        self.assertEqual(score, 100)

    def test_blank_request_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            EvaluationRunRequest(user_id="user-1", request="          ")

    def test_criteria_weights_must_total_100(self) -> None:
        with self.assertRaisesRegex(ValueError, "합계는 100"):
            validate_criteria([{"criterion_key": "a", "required_text": "A", "weight": 90, "mandatory": True}])

    def test_valid_criteria_are_accepted(self) -> None:
        self.assertIsNone(validate_criteria([
            {"criterion_key": "a", "required_text": "A", "weight": 60, "mandatory": True},
            {"criterion_key": "b", "required_text": "B", "weight": 40, "mandatory": False},
        ]))


if __name__ == "__main__": unittest.main()
