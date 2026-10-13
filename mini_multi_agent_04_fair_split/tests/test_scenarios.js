// docs/SCENARIOS.md 의 A. 계산 규칙 시나리오(S1~S8) 자동 검사
// 실행: node tests/test_scenarios.js
const assert = require("assert");
const { computeSplit } = require("../core/calc.js");

const mk = names => names.map((n, i) => ({ id: "p" + i, name: n }));
const a = (here, drink, eat) => ({ here, drink, eat });
const P4 = mk(["A", "B", "C", "D"]), P3 = mk(["A", "B", "C"]);
const all4 = (drink = [1, 1, 1, 1], eat = [1, 1, 1, 1]) => Object.fromEntries(P4.map((p, i) => [p.id, a(true, !!drink[i], eat[i])]));
const all3 = (drink = true) => Object.fromEntries(P3.map(p => [p.id, a(true, drink, 1)]));
const round = (id, payerId, attend, items) => ({ id, name: id === "r1" ? "1차" : "2차", payerId, attend, items });
const food = n => ({ label: "고기", amount: n, kind: "food" });
const alc = n => ({ label: "술", amount: n, kind: "alcohol" });
const twoRounds = payer2 => ({ unit: 100, people: P4, rounds: [
  round("r1", "p0", all4(), [food(80000)]),
  round("r2", payer2, { p0: a(true, true, 1), p1: a(true, true, 1), p2: a(false, false, 1), p3: a(false, false, 1) }, [alc(30000)])] });

const charged = res => res.rows.map(r => r.charged);
const tf = res => res.transfers.map(t => `${t.fromName}->${t.toName} ${t.amount}`).sort();
const test = (name, fn) => { try { fn(); console.log("✓", name); } catch (e) { console.log("✗", name, "\n ", e.message); process.exitCode = 1; } };

test("S1 기본 N빵", () => {
  const res = computeSplit({ unit: 100, people: P4, rounds: [round("r1", "p0", all4(), [food(80000), alc(20000)])] });
  assert.deepStrictEqual(charged(res), [25000, 25000, 25000, 25000]);
});
test("S2 술 안 마신 사람", () => {
  const res = computeSplit({ unit: 100, people: P4, rounds: [round("r1", "p0", all4([1, 1, 0, 0]), [food(80000), alc(20000)])] });
  assert.deepStrictEqual(charged(res), [30000, 30000, 20000, 20000]);
});
test("S3 먹은 양 차이", () => {
  const res = computeSplit({ unit: 100, people: P4, rounds: [round("r1", "p0", all4(undefined, [1, 1.5, 0.5, 1]), [food(80000)])] });
  assert.deepStrictEqual(charged(res), [20000, 30000, 10000, 20000]);
});
test("S4 일찍 간 사람은 2차 0원", () => {
  const res = computeSplit(twoRounds("p0"));
  assert.deepStrictEqual(charged(res), [35000, 35000, 20000, 20000]);
  assert.strictEqual(res.rows[2].perRound.r2.charged, 0);
});
test("S5 결제자가 다르면 상계", () => {
  const res = computeSplit(twoRounds("p1"));
  assert.deepStrictEqual(tf(res), ["B->A 5000", "C->A 20000", "D->A 20000"]);
});
test("S6 나누어떨어지지 않으면 올림", () => {
  const res = computeSplit({ unit: 100, people: P3, rounds: [round("r1", "p0", all3(), [{ label: "안주", amount: 10000, kind: "equal" }])] });
  assert.deepStrictEqual(tf(res), ["B->A 3400", "C->A 3400"]);
  assert.strictEqual(res.surplus, 133);
});
test("S7 혼자 시킨 메뉴", () => {
  const res = computeSplit({ unit: 100, people: P3, rounds: [round("r1", "p0", all3(), [{ label: "피자", amount: 30000, kind: "food" }, { label: "콜라", amount: 3000, kind: "personal", ownerId: "p2" }])] });
  assert.deepStrictEqual(charged(res), [10000, 10000, 13000]);
});
test("S8 입력 실수는 경고", () => {
  const res = computeSplit({ unit: 100, people: P3, rounds: [round("r1", "", all3(false), [alc(9000)])] });
  assert.strictEqual(res.warnings.length, 2);
  assert.strictEqual(res.transfers.length, 0);
  assert.deepStrictEqual(charged(res), [3000, 3000, 3000]);
});
