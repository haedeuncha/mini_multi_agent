// 정산 계산 순수 함수 (페이지와 테스트에서 같이 사용)
function computeSplit(state) {
  const people = state.people;
  const pname = Object.fromEntries(people.map(p => [p.id, p.name]));
  const unit = Number(state.unit) || 1;
  const owe = {};            // owe[pid][rid] = 정확한 금액(소수)
  const detail = {};         // detail[pid] = [{round, label, kind, amount}]
  const warnings = [];
  people.forEach(p => { owe[p.id] = {}; detail[p.id] = []; });

  const add = (pid, r, label, kind, amt) => {
    if (!(pid in owe)) return;
    owe[pid][r.id] = (owe[pid][r.id] || 0) + amt;
    detail[pid].push({ round: r.name, label, kind, amount: amt });
  };

  for (const r of state.rounds) {
    const at = r.attend || {};
    const here = people.filter(p => at[p.id] && at[p.id].here);
    if (!here.length) { if (r.items.some(i => i.amount > 0)) warnings.push(`${r.name}: 참석자가 없어 계산에서 빠졌어요.`); continue; }
    for (const it of r.items) {
      const amt = Number(it.amount) || 0;
      if (amt <= 0) continue;
      if (it.kind === "personal") {
        if (!it.ownerId || !(it.ownerId in owe)) { warnings.push(`${r.name} · ${it.label}: 누가 먹었는지 골라 주세요. 일단 참석자 균등으로 나눴어요.`); here.forEach(p => add(p.id, r, it.label, "equal", amt / here.length)); continue; }
        add(it.ownerId, r, it.label, "personal", amt);
      } else if (it.kind === "alcohol") {
        let drinkers = here.filter(p => at[p.id].drink);
        if (!drinkers.length) { warnings.push(`${r.name} · ${it.label}: 술 마신 사람이 없어서 참석자 균등으로 나눴어요.`); drinkers = here; }
        drinkers.forEach(p => add(p.id, r, it.label, "alcohol", amt / drinkers.length));
      } else if (it.kind === "food") {
        const w = here.map(p => Number(at[p.id].eat) || 1);
        const sum = w.reduce((a, b) => a + b, 0);
        here.forEach((p, i) => add(p.id, r, it.label, "food", amt * w[i] / sum));
      } else {
        here.forEach(p => add(p.id, r, it.label, "equal", amt / here.length));
      }
    }
  }

  // 반올림: 사람별 · 차수별 금액을 단위로 올림 (결제자 본인 몫은 올림하지 않음)
  const roundUp = v => (v <= 0 ? 0 : Math.ceil(v / unit - 1e-9) * unit);
  const rows = people.map(p => {
    const perRound = {};
    let exact = 0, charged = 0;
    for (const r of state.rounds) {
      const v = owe[p.id][r.id] || 0;
      exact += v;
      const c = r.payerId === p.id ? v : roundUp(v);
      perRound[r.id] = { exact: v, charged: c };
      charged += c;
    }
    return { id: p.id, name: p.name, perRound, exact, charged };
  });

  // 송금: 각 차수 결제자에게 보낼 금액 → 서로 주고받는 건 상계
  const debt = {};
  for (const r of state.rounds) {
    if (!r.payerId || !(r.payerId in owe)) { if (r.items.some(i => i.amount > 0)) warnings.push(`${r.name}: 결제한 사람을 골라 주세요.`); continue; }
    for (const row of rows) {
      if (row.id === r.payerId) continue;
      const c = row.perRound[r.id].charged;
      if (c > 0) {
        const k = row.id + ">" + r.payerId;
        debt[k] = (debt[k] || 0) + c;
      }
    }
  }
  const transfers = [];
  const seen = new Set();
  for (const k of Object.keys(debt)) {
    const [a, b] = k.split(">");
    const pair = [a, b].sort().join("|");
    if (seen.has(pair)) continue;
    seen.add(pair);
    const net = (debt[a + ">" + b] || 0) - (debt[b + ">" + a] || 0);
    if (net > 0) transfers.push({ from: a, to: b, amount: net, fromName: pname[a], toName: pname[b] });
    else if (net < 0) transfers.push({ from: b, to: a, amount: -net, fromName: pname[b], toName: pname[a] });
  }

  const roundTotals = state.rounds.map(r => ({ id: r.id, name: r.name, total: r.items.reduce((s, i) => s + (Number(i.amount) || 0), 0) }));
  const grand = roundTotals.reduce((s, r) => s + r.total, 0);
  const collected = rows.reduce((s, r) => s + r.charged, 0);
  return { rows, transfers, detail, warnings, roundTotals, grand, surplus: Math.round(collected - grand) };
}
if (typeof module !== "undefined") module.exports = { computeSplit };
