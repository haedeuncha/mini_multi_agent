"""[Workshop] Lab 10 · 공정 N빵 Supervisor–Worker 테스트 (LLM·MCP 없이 run_profile을 대체)."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.agents.registry import agents_in_group, get_agent  # noqa: E402
from app.orchestration.split_calculator import compute_split  # noqa: E402
from app.orchestration.split_flow import split_settlement_flow  # noqa: E402
from app.schemas.split import SplitRequest  # noqa: E402
from mcp_server.tools.split_tools import get_gathering_members, get_menu_categories, get_receipt  # noqa: E402

MSG = ("GATHER-0930 정산해 줘. 서준이랑 하은이는 술 안 마셨고 1차만 있다 갔어. "
       "도윤이는 많이 먹었고 지영이는 조금 먹었어. 사이다는 하은이 거야.")


def sup(next_agent):
    return {"status": "completed", "result": {"agent_id": "split_supervisor_agent", "next_agent": next_agent, "reason": "State"}}


def worker(payload, tools=None):
    return {"status": "completed", "result": payload, "tool_results": tools or {}}


RECEIPT = worker({"agent_id": "receipt_agent", "unreadable_lines": [], "rounds": [
    {"round_id": "R1", "round_name": "1차 삼겹살집", "payer": "민수", "items": [
        {"label": "삼겹살 5인분", "amount": 64000}, {"label": "물냉면", "amount": 12000},
        {"label": "공기밥", "amount": 3000}, {"label": "된장찌개", "amount": 3000},
        {"label": "참이슬", "amount": 25000}, {"label": "카스", "amount": 10000},
        {"label": "칠성사이다", "amount": 2000}]},
    {"round_id": "R2", "round_name": "2차 호프", "payer": "지영", "items": [
        {"label": "후라이드치킨", "amount": 22000}, {"label": "생맥주 3000cc", "amount": 21000}]}]},
    {"get_receipt": get_receipt("GATHER-0930")})

P = lambda name, rounds, drinks, eat: {"name": name, "rounds_attended": rounds, "drinks": drinks, "eat": eat}  # noqa: E731
SITUATION = worker({"agent_id": "situation_agent", "missing_information": [], "people": [
    P("민수", ["R1", "R2"], True, "보통"), P("지영", ["R1", "R2"], True, "적게"),
    P("서준", ["R1"], False, "보통"), P("하은", ["R1"], False, "보통"), P("도윤", ["R1", "R2"], True, "많이")]},
    {"get_gathering_members": get_gathering_members("GATHER-0930")})

K = lambda r, label, kind, owner=None: {"round_id": r, "label": label, "kind": kind, "owner": owner}  # noqa: E731
CLASSIFY = worker({"agent_id": "classifier_agent", "items": [
    K("R1", "삼겹살 5인분", "food"), K("R1", "물냉면", "food"), K("R1", "공기밥", "food"), K("R1", "된장찌개", "food"),
    K("R1", "참이슬", "alcohol"), K("R1", "카스", "alcohol"), K("R1", "칠성사이다", "personal", "하은"),
    K("R2", "후라이드치킨", "food"), K("R2", "생맥주 3000cc", "alcohol")]},
    {"get_menu_categories": get_menu_categories()})

EXPLAIN_OK = worker({"agent_id": "explainer_agent", "lines": [
    {"name": "서준", "text": "술을 마시지 않고 1차만 있어서 16,400원입니다."}]})
EXPLAIN_BAD = worker({"agent_id": "explainer_agent", "lines": [
    {"name": "서준", "text": "대략 15,000원 정도입니다."}]})

EXPECTED_TRANSFERS = ["도윤->민수 36300", "도윤->지영 14400", "서준->민수 16400", "지영->민수 5500", "하은->민수 18400"]


def transfers(result):
    return sorted(f"{t['from']}->{t['to']} {t['amount']}" for t in result["settlement"]["transfers"])


async def run(responses, message=MSG):
    with patch("app.orchestration.split_flow.run_profile", new_callable=AsyncMock, side_effect=responses) as mock:
        result = await split_settlement_flow(SplitRequest(message=message))
    return result, mock


class Lab10RegistryTests(unittest.TestCase):
    def test_yaml_workers_and_python_supervisor_are_registered(self):
        group = agents_in_group("split")
        self.assertEqual(set(group), {"split_supervisor_agent", "receipt_agent", "situation_agent",
                                      "classifier_agent", "explainer_agent"})
        self.assertEqual(get_agent("receipt_agent").allowed_tools, frozenset({"get_receipt"}))
        self.assertEqual(get_agent("explainer_agent").allowed_tools, frozenset())

    def test_mock_tools_return_source(self):
        self.assertEqual(get_receipt("gather-0930")["source"], "mock:split_gatherings.json")
        self.assertEqual(len(get_receipt("GATHER-1004")["receipts"]), 3)
        self.assertEqual(len(get_receipt("GATHER-1005")["receipts"]), 4)
        self.assertFalse(get_receipt("GATHER-9999")["success"])


class Lab10CalculatorTests(unittest.TestCase):
    def test_all_attendees_drink_splits_every_item_equally(self):
        members = ["A", "B", "C"]
        rounds = [{"round_id": "R1", "round_name": "회식", "payer": "A"}]
        people = [P("A", ["R1"], True, "많이"), P("B", ["R1"], True, "적게"), P("C", ["R1"], True, "보통")]
        items = [
            K("R1", "식사", "food") | {"amount": 60000},
            K("R1", "맥주", "alcohol") | {"amount": 24000},
            K("R1", "개인 음료", "personal", "B") | {"amount": 6000},
        ]

        out = compute_split(members, rounds, people, items)

        self.assertEqual([r["total"] for r in out["rows"]], [30000, 30000, 30000])
        self.assertEqual(out["transfers"], [{"from": "B", "to": "A", "amount": 30000}, {"from": "C", "to": "A", "amount": 30000}])
        self.assertTrue(any("전원 N빵" in warning for warning in out["warnings"]))

    def test_three_rounds_are_calculated_independently(self):
        members = ["A", "B", "C", "D"]
        rounds = [
            {"round_id": "R1", "round_name": "저녁", "payer": "A"},
            {"round_id": "R2", "round_name": "카페", "payer": "B"},
            {"round_id": "R3", "round_name": "택시", "payer": "D"},
        ]
        people = [P(name, ["R1", "R2", "R3"], False, "보통") for name in members]
        items = [
            K("R1", "저녁 식사", "food") | {"amount": 100000},
            K("R2", "커피와 디저트", "food") | {"amount": 24000},
            K("R3", "택시", "equal") | {"amount": 32000},
        ]

        out = compute_split(members, rounds, people, items)

        self.assertEqual([row["per_round"] for row in out["rows"]], [
            {"R1": 25000, "R2": 6000, "R3": 8000},
            {"R1": 25000, "R2": 6000, "R3": 8000},
            {"R1": 25000, "R2": 6000, "R3": 8000},
            {"R1": 25000, "R2": 6000, "R3": 8000},
        ])
        self.assertEqual(out["grand_total"], 156000)
        self.assertEqual(out["collected"], 156000)

    def test_non_drinker_pays_no_alcohol_and_early_leaver_skips_round2(self):
        members = ["A", "B", "C", "D"]
        rounds = [{"round_id": "R1", "round_name": "1차", "payer": "A"}, {"round_id": "R2", "round_name": "2차", "payer": "B"}]
        people = [P("A", ["R1", "R2"], True, "보통"), P("B", ["R1", "R2"], True, "보통"),
                  P("C", ["R1"], False, "보통"), P("D", ["R1"], False, "보통")]
        items = [K("R1", "고기", "food") | {"amount": 80000}, K("R1", "술", "alcohol") | {"amount": 20000},
                 K("R2", "맥주", "alcohol") | {"amount": 30000}]
        out = compute_split(members, rounds, people, items)
        self.assertEqual([r["total"] for r in out["rows"]], [45000, 45000, 20000, 20000])
        self.assertIn({"from": "B", "to": "A", "amount": 15000}, out["transfers"])


class Lab10FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_flow_completes_with_python_settlement(self):
        result, mock = await run([sup("receipt_agent"), RECEIPT, sup("situation_agent"), SITUATION,
                                  sup("classifier_agent"), CLASSIFY, sup("explainer_agent"), EXPLAIN_OK, sup("finish")])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(mock.await_count, 9)
        self.assertEqual(transfers(result), EXPECTED_TRANSFERS)
        actors = [t["actor"] for t in result["trace"]]
        self.assertIn("python_calculator", actors)
        # 최소 Context: 분류 Agent Prompt에는 금액이 없다
        classifier_prompt = mock.await_args_list[5].args[1]
        self.assertNotIn("64000", classifier_prompt)
        self.assertNotIn("64,000", classifier_prompt)

    async def test_missing_gathering_id_asks_user_without_llm(self):
        result, mock = await run([], message="어제 회식비 정산해 줘")
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(mock.await_count, 0)

    async def test_receipt_total_mismatch_stops_for_human(self):
        mismatch = worker({"agent_id": "receipt_agent", "unreadable_lines": ["#### ▒▒▒ (판독 불가) ....... ▒,▒▒▒"], "rounds": [
            {"round_id": "R1", "round_name": "1차 분식집", "payer": "가은", "items": [
                {"label": "떡볶이", "amount": 15000}, {"label": "순대", "amount": 12000},
                {"label": "모둠튀김", "amount": 10000}, {"label": "맥주", "amount": 20000}]}]},
            {"get_receipt": get_receipt("GATHER-1001")})
        result, mock = await run([sup("receipt_agent"), mismatch], message="GATHER-1001 정산해 줘. 다들 술 마셨어.")
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("차이 3,000원", result["reason"])
        self.assertEqual(mock.await_count, 2)

    async def test_invented_amount_is_rejected(self):
        bad = worker({**RECEIPT["result"], "rounds": [dict(RECEIPT["result"]["rounds"][0], items=[{"label": "삼겹살", "amount": 70000}]),
                                                         RECEIPT["result"]["rounds"][1]]}, RECEIPT["tool_results"])
        result, _ = await run([sup("receipt_agent"), bad])
        self.assertEqual(result["status"], "failed")
        self.assertIn("원문에 없는 금액", result["trace"][-1]["verification_error"])

    async def test_unknown_name_needs_information(self):
        unknown = worker({**SITUATION["result"], "missing_information": ["은비는 멤버가 아닙니다. 추가할까요?"]},
                         SITUATION["tool_results"])
        result, mock = await run([sup("receipt_agent"), RECEIPT, sup("situation_agent"), unknown])
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(mock.await_count, 4)

    async def test_supervisor_wrong_order_is_blocked(self):
        result, _ = await run([sup("classifier_agent")])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "invalid_transition")

    async def test_optional_explainer_with_wrong_amount_gives_partial(self):
        result, _ = await run([sup("receipt_agent"), RECEIPT, sup("situation_agent"), SITUATION,
                               sup("classifier_agent"), CLASSIFY, sup("explainer_agent"), EXPLAIN_BAD, sup("finish")])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(transfers(result), EXPECTED_TRANSFERS)


if __name__ == "__main__":
    unittest.main()


# ── SCENARIOS_LAB10.md 추가 시나리오 ─────────────────────────────────────
class Lab10ScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_N3_study_group_driver_skips_cafe(self):
        receipt = worker({"agent_id": "receipt_agent", "unreadable_lines": [], "rounds": [
            {"round_id": "R1", "round_name": "1차 파스타집", "payer": "수아", "items": [
                {"label": "크림파스타", "amount": 15000}, {"label": "토마토파스타", "amount": 14000},
                {"label": "마르게리타피자", "amount": 20000}, {"label": "시저샐러드", "amount": 11000},
                {"label": "하우스와인 1병", "amount": 30000}, {"label": "콜라", "amount": 3000}]},
            {"round_id": "R2", "round_name": "2차 카페", "payer": "준호", "items": [
                {"label": "아메리카노 x3", "amount": 13500}, {"label": "치즈케이크", "amount": 7500}]}]},
            {"get_receipt": get_receipt("GATHER-1003")})
        situation = worker({"agent_id": "situation_agent", "missing_information": [], "people": [
            P("수아", ["R1", "R2"], True, "보통"), P("준호", ["R1", "R2"], True, "보통"),
            P("민지", ["R1", "R2"], True, "적게"), P("태윤", ["R1"], False, "보통")]},
            {"get_gathering_members": get_gathering_members("GATHER-1003")})
        classify = worker({"agent_id": "classifier_agent", "items": [
            K("R1", "크림파스타", "food"), K("R1", "토마토파스타", "food"), K("R1", "마르게리타피자", "food"),
            K("R1", "시저샐러드", "food"), K("R1", "하우스와인 1병", "alcohol"), K("R1", "콜라", "personal", "태윤"),
            K("R2", "아메리카노 x3", "food"), K("R2", "치즈케이크", "food")]})
        result, _ = await run([sup("receipt_agent"), receipt, sup("situation_agent"), situation,
                               sup("classifier_agent"), classify, sup("explainer_agent"),
                               worker(None) | {"result": None, "error": "gemma timeout"}, sup("finish")],
                              message="GATHER-1003 정산해 줘.")
        self.assertEqual(result["status"], "partial")          # P2: 설명 Provider 실패도 partial
        self.assertEqual(transfers(result), ["민지->수아 18600", "민지->준호 7000", "준호->수아 20200", "태윤->수아 20200"])
        taeyun = next(r for r in result["settlement"]["rows"] if r["name"] == "태윤")
        self.assertEqual(taeyun["per_round"]["R2"], 0)

    async def test_I3_payer_not_member_needs_information(self):
        receipt = worker({"agent_id": "receipt_agent", "unreadable_lines": [], "rounds": [
            {"round_id": "R1", "round_name": "1차 마트 장보기", "payer": "동아리회비카드", "items": [
                {"label": "목살 1kg", "amount": 28000}, {"label": "라면 x5", "amount": 5000},
                {"label": "생수 2L x6", "amount": 6000}, {"label": "소주 x6", "amount": 12000}]}]},
            {"get_receipt": get_receipt("GATHER-1002")})
        situation = worker({"agent_id": "situation_agent", "missing_information": [], "people": [
            P("라온", ["R1"], True, "보통"), P("마루", ["R1"], True, "보통"), P("바다", ["R1"], True, "보통")]},
            {"get_gathering_members": get_gathering_members("GATHER-1002")})
        result, mock = await run([sup("receipt_agent"), receipt, sup("situation_agent"), situation],
                                 message="GATHER-1002 정산해 줘. 셋 다 술 마셨어.")
        self.assertEqual(result["status"], "needs_information")
        self.assertIn("동아리회비카드", result["reason"])
        self.assertEqual(mock.await_count, 4)

    async def test_F3_classifier_missing_menu_fails(self):
        partial_items = worker({"agent_id": "classifier_agent", "items": CLASSIFY["result"]["items"][:-1]})
        result, _ = await run([sup("receipt_agent"), RECEIPT, sup("situation_agent"), SITUATION,
                               sup("classifier_agent"), partial_items])
        self.assertEqual(result["status"], "failed")
        self.assertIn("메뉴 누락", result["trace"][-1]["verification_error"])
        self.assertIsNone(result["settlement"])                 # 계산하지 않는다

    async def test_F4_personal_owner_not_in_round_fails(self):
        items = [dict(i) for i in CLASSIFY["result"]["items"]]
        items[-2] = K("R2", "후라이드치킨", "personal", "서준")    # 서준은 2차에 없었다
        result, _ = await run([sup("receipt_agent"), RECEIPT, sup("situation_agent"), SITUATION,
                               sup("classifier_agent"), worker({"agent_id": "classifier_agent", "items": items})])
        self.assertEqual(result["status"], "failed")
        self.assertIn("R2에 없습니다", result["trace"][-1]["verification_error"])

    async def test_F5_supervisor_provider_failure_stops(self):
        down = {"status": "failed", "result": None, "error": "openai Provider 호출에 실패했습니다: APIConnectionError"}
        result, mock = await run([down])
        self.assertEqual((result["status"], result["reason"]), ("failed", "supervisor_failed"))
        self.assertEqual(mock.await_count, 1)

    async def test_F6_unknown_gathering_fails_after_tool(self):
        empty = worker({"agent_id": "receipt_agent", "unreadable_lines": [], "rounds": [
            {"round_id": "R1", "round_name": "알 수 없음", "payer": "없음", "items": [{"label": "없음", "amount": 1}]}]},
            {"get_receipt": get_receipt("GATHER-9999")})
        result, _ = await run([sup("receipt_agent"), empty], message="GATHER-9999 정산해 줘.")
        self.assertEqual(result["status"], "failed")
        self.assertIn("찾을 수 없습니다", result["reason"])
