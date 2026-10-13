"""[Workshop 4] Lab 10 · 결정적 정산 계산 (LLM 사용 안 함).

04 프로젝트 core/calc.js의 computeSplit()을 Python으로 옮긴 것이다.
- food: 그 차수 참석자가 먹은 양(적게 0.5 · 보통 1 · 많이 1.5) 비율로
- alcohol: 그 차수에서 술 마신 사람끼리 균등 (없으면 참석자 균등 + 경고)
- equal: 그 차수 참석자 균등
- personal: owner 혼자
- 해당 차수의 참석자가 모두 술을 마셨다면: 메뉴 종류와 개인 주문 구분 없이 차수 총액을 참석자 전원 N빵
받을 돈은 unit 단위로 올림, 결제자 본인 몫은 올림하지 않는다. 송금은 서로 상계한다.
"""

import math

EAT_WEIGHT = {"적게": 0.5, "보통": 1.0, "많이": 1.5}


def compute_split(members: list[str], rounds: list[dict], people: list[dict],
                  items: list[dict], unit: int = 100) -> dict:
    state = {p["name"]: p for p in people}
    owe = {m: {r["round_id"]: 0.0 for r in rounds} for m in members}
    detail = {m: [] for m in members}
    warnings: list[str] = []

    def add(name, round_id, label, kind, amount):
        owe[name][round_id] += amount
        detail[name].append({"round_id": round_id, "label": label, "kind": kind, "amount": round(amount, 2)})

    for r in rounds:
        rid = r["round_id"]
        here = [m for m in members if rid in state[m]["rounds_attended"]]
        round_items = [i for i in items if i["round_id"] == rid]
        if not here:
            warnings.append(f"{r['round_name']}: 참석자가 없어 계산에서 제외했습니다.")
            continue
        # 모두 음주한 회식은 '누가 무엇을 더 먹었는지'보다 함께한 비용이라는 합의가 우선입니다.
        # 요청 문장에서 모든 참석자의 drinks=True가 확정된 경우에만 이 규칙을 적용합니다.
        all_attendees_drink = all(state[m]["drinks"] for m in here)
        if all_attendees_drink:
            warnings.append(f"{r['round_name']}: 참석자 전원이 음주하여 차수 총액을 전원 N빵했습니다.")
            for it in round_items:
                for m in here:
                    add(m, rid, it["label"], "all_drinkers_equal", it["amount"] / len(here))
            continue
        for it in round_items:
            amount = it["amount"]
            if it["kind"] == "personal":
                add(it["owner"], rid, it["label"], "personal", amount)
            elif it["kind"] == "alcohol":
                drinkers = [m for m in here if state[m]["drinks"]]
                if not drinkers:
                    warnings.append(f"{r['round_name']} · {it['label']}: 술 마신 사람이 없어 참석자 균등으로 나눴습니다.")
                    drinkers = here
                for m in drinkers:
                    add(m, rid, it["label"], "alcohol", amount / len(drinkers))
            elif it["kind"] == "food":
                weights = {m: EAT_WEIGHT[state[m]["eat"]] for m in here}
                total_w = sum(weights.values())
                for m in here:
                    add(m, rid, it["label"], "food", amount * weights[m] / total_w)
            else:
                for m in here:
                    add(m, rid, it["label"], "equal", amount / len(here))

    def round_up(value: float) -> int:
        return 0 if value <= 0 else int(math.ceil(value / unit - 1e-9) * unit)

    payer_of = {r["round_id"]: r["payer"] for r in rounds}
    rows = []
    for m in members:
        per_round = {}
        for r in rounds:
            exact = owe[m][r["round_id"]]
            per_round[r["round_id"]] = round(exact) if payer_of[r["round_id"]] == m else round_up(exact)
        rows.append({"name": m, "per_round": per_round, "total": sum(per_round.values()),
                     "exact_total": round(sum(owe[m].values()))})

    debt: dict[tuple[str, str], int] = {}
    for r in rounds:
        payer = r["payer"]
        for row in rows:
            if row["name"] != payer and row["per_round"][r["round_id"]] > 0:
                key = (row["name"], payer)
                debt[key] = debt.get(key, 0) + row["per_round"][r["round_id"]]
    transfers, seen = [], set()
    for a, b in debt:
        pair = tuple(sorted((a, b)))
        if pair in seen:
            continue
        seen.add(pair)
        net = debt.get((a, b), 0) - debt.get((b, a), 0)
        if net > 0:
            transfers.append({"from": a, "to": b, "amount": net})
        elif net < 0:
            transfers.append({"from": b, "to": a, "amount": -net})

    grand = sum(i["amount"] for i in items)
    return {"rows": rows, "transfers": transfers, "detail": detail, "warnings": warnings,
            "grand_total": grand, "collected": sum(r["total"] for r in rows), "unit": unit}
