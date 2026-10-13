"""[Workshop 4] Lab 10 · 공정 N빵 정산 Supervisor–Worker Orchestration.

engine.py의 supervisor_loop()(88라인 부근)과 같은 뼈대를 사용한다.

    while 호출 수 < 최대:
        expected = Python이 계산한 다음 허용 행동
        Supervisor(LLM)가 다음 Agent 제안  → expected와 다르면 invalid_transition으로 차단
        finish면 종료
        Worker 실행 → 계약 + Python Guard 검증 → State에 저장

engine.py와 달라진 점
1. 순서가 고정 목록이 아니라 State(검증된 결과)로 결정된다. → expected_next()
2. Worker마다 필요한 최소 Context만 전달한다. → worker_prompt()
3. 계약 통과 뒤에도 업무 규칙을 Python이 한 번 더 검사한다. → verify_worker()
   (영수증 합계, 멤버 이름, 메뉴 누락, 설명 속 금액)
4. 금액 계산은 LLM이 아닌 split_calculator.compute_split()이 한다.
5. 필수 Worker 실패는 중단, 선택 Worker(explainer_agent) 실패는 partial로 계속한다.
"""

import json
import re

from pydantic import ValidationError

from app.agents.registry import get_agent
from app.agents.runtime import run_profile
from app.orchestration.split_calculator import compute_split
from app.schemas.split import (
    SplitClassificationResult, SplitExplanationResult, SplitReceiptResult, SplitRequest,
    SplitSituationResult, SplitSupervisorDecision,
)

MAX_LLM_CALLS = 9          # Supervisor 5회 + Worker 4회
OPTIONAL_WORKERS = {"explainer_agent"}
WORKER_SCHEMAS = {
    "receipt_agent": SplitReceiptResult,
    "situation_agent": SplitSituationResult,
    "classifier_agent": SplitClassificationResult,
    "explainer_agent": SplitExplanationResult,
}
GATHER_PATTERN = re.compile(r"\bGATHER[-_ ]?\d+\b", re.IGNORECASE)
EAT_LABEL = {"적게": "조금", "보통": "보통", "많이": "많이"}


def new_state(gathering_id: str, unit: int) -> dict:
    return {"gathering_id": gathering_id, "unit": unit, "receipt": None, "raw_receipts": None,
            "members": None, "situation": None, "classification": None, "settlement": None,
            "explanation": None, "explainer_failed": False}


def expected_next(state: dict) -> str:
    """State만 보고 지금 허용되는 다음 행동 하나를 Python이 계산한다."""
    if state["receipt"] is None:
        return "receipt_agent"
    if state["situation"] is None:
        return "situation_agent"
    if state["classification"] is None:
        return "classifier_agent"
    if state["explanation"] is None and not state["explainer_failed"]:
        return "explainer_agent"
    return "finish"


# ── 최소 Context ─────────────────────────────────────────────────────────
def worker_prompt(agent_id: str, request: SplitRequest, state: dict) -> str:
    profile = get_agent(agent_id)
    head = f"당신은 {agent_id}입니다.\nGoal: {profile.goal}\nInstructions: {profile.instructions}\n"
    gid = state["gathering_id"]
    if agent_id == "receipt_agent":
        # 영수증 원문은 run_profile이 get_receipt Tool 결과로 붙여 준다. 사용자 문장은 필요 없다.
        return head + f"모임 ID: {gid}\nround_id·round_name은 Tool 결과 값을 그대로 쓰세요. SplitReceiptResult로 반환하세요."
    if agent_id == "situation_agent":
        # 금액·메뉴는 전달하지 않는다. 사용자 문장과 (Tool로 받는) 멤버 목록만 본다.
        return head + (f"모임 ID: {gid}\n사용자 문장: {request.message}\n"
                       "rounds_attended에는 Tool 결과의 round_id(R1, R2 …)를 쓰세요. "
                       "eat은 적게·보통·많이 중 하나입니다. SplitSituationResult로 반환하세요.")
    if agent_id == "classifier_agent":
        # 금액은 빼고 메뉴 이름만 전달한다.
        menus = [{"round_id": r["round_id"], "label": i["label"]}
                 for r in state["receipt"]["rounds"] for i in r["items"]]
        return head + (f"분류할 메뉴(금액 제외): {json.dumps(menus, ensure_ascii=False)}\n"
                       f"멤버: {state['members']}\n사용자 문장(누구 거 언급 확인용): {request.message}\n"
                       "모든 메뉴를 빠짐없이, round_id·label을 그대로 옮겨 SplitClassificationResult로 반환하세요.")
    # explainer_agent: 이름·금액·이유 재료만 전달한다. 다른 사람 영수증 원문은 주지 않는다.
    people = []
    situation = {p["name"]: p for p in state["situation"]["people"]}
    for row in state["settlement"]["rows"]:
        kinds = {}
        for d in state["settlement"]["detail"][row["name"]]:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + d["amount"]
        p = situation[row["name"]]
        people.append({"name": row["name"], "total": row["total"],
                       "rounds_attended": p["rounds_attended"], "drinks": p["drinks"], "eat": p["eat"],
                       "alcohol_share": round(kinds.get("alcohol", 0))})
    return head + (f"계산 결과(수정 금지): {json.dumps(people, ensure_ascii=False)}\n"
                   "금액을 말할 때는 total 값만 쓰세요. SplitExplanationResult로 반환하세요.")


# ── 계약 + 업무 규칙 Guard ────────────────────────────────────────────────
def _tool(response: dict, name: str) -> dict:
    return (response.get("tool_results") or {}).get(name) or {}


def verify_worker(agent_id: str, response: dict, state: dict):
    """(검증된 결과 dict, 오류 문구, 종료 상태)를 반환한다. 종료 상태가 있으면 Loop를 멈춘다."""
    payload = response.get("result")
    if payload is None:
        return None, response.get("error") or "Worker 결과가 없습니다.", None
    try:
        verified = WORKER_SCHEMAS[agent_id].model_validate(payload).model_dump()
    except ValidationError as error:
        return None, str(error), None

    if agent_id == "receipt_agent":
        tool = _tool(response, "get_receipt")
        if not tool.get("success"):
            return None, tool.get("error", "영수증 Tool 조회 실패"), "failed"
        raw = {r["round_id"]: r for r in tool["receipts"]}
        if {r["round_id"] for r in verified["rounds"]} != set(raw):
            return None, f"차수 불일치: Tool={sorted(raw)}", None
        for r in verified["rounds"]:
            text = " ".join(raw[r["round_id"]]["raw_lines"])
            invented = [i["label"] for i in r["items"] if f"{i['amount']:,}" not in text]
            if invented:
                return None, f"{r['round_name']}: 영수증 원문에 없는 금액 {invented}", None
            total = sum(i["amount"] for i in r["items"])
            printed = raw[r["round_id"]]["printed_total"]
            if total != printed:
                # 추측으로 맞추지 않고 사람에게 넘긴다 (시나리오 F1)
                return verified, (f"{r['round_name']}: 메뉴 합계 {total:,}원 ≠ 영수증 합계 {printed:,}원 "
                                  f"(차이 {printed - total:,}원). 판독 불가 줄: {verified['unreadable_lines']}"), "needs_attention"
        return verified, None, None

    if agent_id == "situation_agent":
        tool = _tool(response, "get_gathering_members")
        members = tool.get("members") or []
        round_ids = {r["round_id"] for r in state["receipt"]["rounds"]}
        if verified["missing_information"]:
            return verified, "사용자 확인 필요: " + " / ".join(verified["missing_information"]), "needs_information"
        names = [p["name"] for p in verified["people"]]
        if sorted(names) != sorted(members):
            return None, f"멤버 불일치: 결과={names}, 멤버={members}", None
        for p in verified["people"]:
            if not set(p["rounds_attended"]) <= round_ids:
                return None, f"{p['name']}: 없는 차수 {p['rounds_attended']}", None
        payers = {r["payer"] for r in state["receipt"]["rounds"]}
        if not payers <= set(members):
            return verified, f"결제자 {sorted(payers - set(members))}가 멤버 목록에 없습니다.", "needs_information"
        state["members"] = members
        return verified, None, None

    if agent_id == "classifier_agent":
        expected = {(r["round_id"], i["label"]) for r in state["receipt"]["rounds"] for i in r["items"]}
        got = {(i["round_id"], i["label"]) for i in verified["items"]}
        if got != expected:
            return None, f"메뉴 누락·추가: 빠짐={sorted(expected - got)}, 추가={sorted(got - expected)}", None
        attend = {p["name"]: p["rounds_attended"] for p in state["situation"]["people"]}
        for i in verified["items"]:
            if i["kind"] == "personal" and i["round_id"] not in attend.get(i["owner"], []):
                return None, f"{i['label']}: owner {i['owner']}가 {i['round_id']}에 없습니다.", None
        return verified, None, None

    # explainer_agent: 설명 속 금액이 Python 계산 결과와 같은지 확인한다 (시나리오 F4)
    totals = {row["name"]: row["total"] for row in state["settlement"]["rows"]}
    allowed = set(totals.values()) | {v for row in state["settlement"]["rows"] for v in row["per_round"].values()}
    for line in verified["lines"]:
        if line["name"] not in totals:
            return None, f"없는 사람 설명: {line['name']}", None
        for num in re.findall(r"(\d[\d,]*)\s*원", line["text"]):
            if int(num.replace(",", "")) not in allowed:
                return None, f"{line['name']} 설명에 계산 결과에 없는 금액 {num}원", None
    return verified, None, None


def settle(state: dict) -> dict:
    """[Python] 검증된 영수증·상황·분류로 결정적 계산을 수행한다."""
    amounts = {(r["round_id"], i["label"]): i["amount"] for r in state["receipt"]["rounds"] for i in r["items"]}
    items = [{**i, "amount": amounts[(i["round_id"], i["label"])]} for i in state["classification"]["items"]]
    rounds = [{"round_id": r["round_id"], "round_name": r["round_name"], "payer": r["payer"]}
              for r in state["receipt"]["rounds"]]
    return compute_split(state["members"], rounds, state["situation"]["people"], items, state["unit"])


def finish(status: str, reason: str, state: dict, trace: list) -> dict:
    return {"status": status, "reason": reason, "state": state, "trace": trace,
            "settlement": state.get("settlement")}


# ── Supervisor–Worker Loop ────────────────────────────────────────────────
async def split_settlement_flow(request: SplitRequest, tracker=None) -> dict:
    match = GATHER_PATTERN.search(request.message)
    if not match:
        # LLM을 부르기 전에 Python이 먼저 되묻는다 (시나리오 I1)
        return finish("needs_information", "gathering_id_missing", new_state("", request.unit),
                      [{"step": 0, "actor": "python_guard", "action": "ask_user",
                        "message": "정산할 모임 번호(예: GATHER-0930)를 알려 주세요."}])
    state = new_state(match.group(0).replace("_", "-").replace(" ", "-").upper(), request.unit)
    trace: list[dict] = []

    def llm_calls() -> int:
        # Python 계산 단계는 LLM 호출 수에 넣지 않는다.
        return sum(1 for t in trace if t["actor"] != "python_calculator")

    while llm_calls() < MAX_LLM_CALLS:
        expected = expected_next(state)
        decision_state = {
            "receipt_done": state["receipt"] is not None,
            "situation_done": state["situation"] is not None,
            "classification_done": state["classification"] is not None,
            "settlement_done": state["settlement"] is not None,
            "explanation_done": state["explanation"] is not None,
            "explainer_failed": state["explainer_failed"],
        }
        supervisor_prompt = (
            "당신은 split_supervisor_agent입니다. 다음 Agent만 고르세요. 금액을 계산하지 마세요.\n"
            f"진행 상태: {json.dumps(decision_state, ensure_ascii=False)}\n"
            f"현재 허용된 next_agent 값은 {expected}입니다. 정확히 이 값을 반환하세요.\n"
            "SplitSupervisorDecision 계약으로 반환하세요."
        )
        supervisor = await run_profile(get_agent("split_supervisor_agent"), supervisor_prompt,
                                       SplitSupervisorDecision, tracker)
        trace.append({"step": len(trace) + 1, "actor": "split_supervisor_agent", "action": "select",
                      "expected_next": expected, **supervisor})
        if supervisor.get("result") is None:
            return finish("failed", "supervisor_failed", state, trace)
        selected = supervisor["result"]["next_agent"]
        if selected != expected:
            return finish("blocked", "invalid_transition", state, trace)
        if selected == "finish":
            done = "completed" if state["explanation"] else "partial"
            return finish(done, "all_workers_completed" if done == "completed" else "explainer_skipped", state, trace)
        if llm_calls() >= MAX_LLM_CALLS:
            break

        worker = await run_profile(get_agent(selected), worker_prompt(selected, request, state),
                                   WORKER_SCHEMAS[selected], tracker)
        verified, error, stop = verify_worker(selected, worker, state)
        trace.append({"step": len(trace) + 1, "actor": selected, "action": "execute",
                      "verification_error": error, **worker})

        if stop:
            if selected == "receipt_agent":
                state["raw_receipts"] = _tool(worker, "get_receipt").get("receipts")
            return finish(stop, error, state, trace)
        if verified is None:
            if selected in OPTIONAL_WORKERS:
                state["explainer_failed"] = True     # 선택 Worker: 기록만 하고 계속 (시나리오 P1)
                continue
            return finish("failed", "worker_failed", state, trace)

        key = {"receipt_agent": "receipt", "situation_agent": "situation",
               "classifier_agent": "classification", "explainer_agent": "explanation"}[selected]
        state[key] = verified
        if selected == "classifier_agent":
            state["settlement"] = settle(state)
            trace.append({"step": len(trace) + 1, "actor": "python_calculator", "action": "compute_split",
                          "status": "completed", "llm": False,
                          "result": {"transfers": state["settlement"]["transfers"],
                                     "grand_total": state["settlement"]["grand_total"]}})
            if tracker:
                tracker.update("python_calculator", "compute_split", "Python 정산 계산 완료", done=True)
    return finish("failed", "max_llm_calls", state, trace)


async def execute_split_tracked(run_id: str, request: SplitRequest) -> None:
    from app.observability.tracker import RunTracker

    tracker = RunTracker(run_id, MAX_LLM_CALLS + 2)
    tracker.update("orchestrator", "queued", "공정 N빵 정산 실행이 등록되었습니다.")
    try:
        result = await split_settlement_flow(request, tracker)
        result["run_id"] = run_id
        if result["status"] in {"completed", "partial"}:
            tracker.finish(result)
        else:
            tracker.fail(f"종료 이유: {result['reason']}", result)
    except Exception as error:
        tracker.fail(f"{type(error).__name__}: {error}")
