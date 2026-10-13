// 실행: node tests/test_calc.js
const assert = require("assert");
const { computeSplit } = require("../core/calc.js");

const P = ["민수", "지영", "서준", "하은", "도윤"].map((n, i) => ({ id: "p" + i, name: n }));
const a = (here, drink, eat) => ({ here, drink, eat });
const base = () => ({ unit: 100, people: P, rounds: [
  { id: "r1", name: "1차", payerId: "p0",
    attend: { p0: a(true, true, 1), p1: a(true, true, 0.5), p2: a(true, false, 1), p3: a(true, false, 1), p4: a(true, true, 1.5) },
    items: [{ label: "삼겹살", amount: 64000, kind: "food" }, { label: "냉면", amount: 18000, kind: "food" },
            { label: "소주", amount: 25000, kind: "alcohol" }, { label: "맥주", amount: 10000, kind: "alcohol" },
            { label: "사이다", amount: 2000, kind: "personal", ownerId: "p3" }] },
  { id: "r2", name: "2차", payerId: "p1",
    attend: { p0: a(true, true, 1), p1: a(true, true, 1), p4: a(true, true, 1) },
    items: [{ label: "치킨", amount: 22000, kind: "food" }, { label: "맥주", amount: 21000, kind: "alcohol" }] }] });

const test = (name, fn) => { try { fn(); console.log("✓", name); } catch (e) { console.log("✗", name, "\n ", e.message); process.exitCode = 1; } };
const by = (res, name) => res.rows.find(r => r.name === name);

test("술 안 마신 사람은 술값을 내지 않는다", () => {
  const res = computeSplit(base());
  assert.ok(res.detail.p2.every(d => d.kind !== "alcohol"));
});
test("많이 먹은 사람은 음식값을 3배(1.5 vs 0.5) 더 낸다", () => {
  const res = computeSplit(base());
  const food = pid => res.detail[pid].filter(d => d.round === "1차" && d.kind === "food").reduce((s, d) => s + d.amount, 0);
  assert.strictEqual(Math.round(food("p4")), Math.round(food("p1") * 3));
});
test("2차에 없던 사람은 2차 비용이 0원", () => {
  const res = computeSplit(base());
  assert.strictEqual(by(res, "서준").perRound.r2.exact, 0);
});
test("혼자 시킨 메뉴는 그 사람만 낸다", () => {
  const res = computeSplit(base());
  assert.ok(res.detail.p3.some(d => d.label === "사이다" && d.amount === 2000));
  assert.ok(!res.detail.p2.some(d => d.label === "사이다"));
});
test("걷는 돈 합계 ≥ 총액, 차이는 반올림 단위 × 인원 이내", () => {
  const res = computeSplit(base());
  assert.strictEqual(res.grand, 162000);
  assert.ok(res.surplus >= 0 && res.surplus < 100 * 5 * 2);
});
test("서로 주고받는 돈은 상계된다 (지영→민수 한 줄만)", () => {
  const res = computeSplit(base());
  const pair = res.transfers.filter(t => [t.from, t.to].sort().join() === "p0,p1");
  assert.strictEqual(pair.length, 1);
  assert.deepStrictEqual([pair[0].fromName, pair[0].toName, pair[0].amount], ["지영", "민수", 5500]);
});
test("술 마신 사람이 없으면 참석자 균등 + 경고", () => {
  const s = base(); s.rounds[1].attend = { p0: a(true, false, 1), p1: a(true, false, 1) };
  const res = computeSplit(s);
  assert.ok(res.warnings.some(w => w.includes("술 마신 사람이 없어서")));
});
