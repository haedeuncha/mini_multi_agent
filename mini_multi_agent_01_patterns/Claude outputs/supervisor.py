"""
계획서(MULTI_AGENT_PROJECT_PROPOSALS.md) 기준 Supervisor
주제: 제안 1. 멀티 에이전트 고객지원 시스템 (계획서 최우선 추천)

계획서 흐름
  고객 문의 → Triage → 전문 Agent Routing/병렬 → Handoff → 결과 검증 → Response → 최종 답변
실행 안정성
  Timeout → 제한된 재시도 → Failover → 필수·선택 구분 → 안전한 중단 → 상담원 이관 → Trace

핵심 원칙 (03강과 동일)
  - LLM은 "판단"만 하고, 실행 순서·권한·종료는 Python Guard가 결정한다.
  - 각 Agent에는 전체 State가 아니라 필요한 최소 Context만 전달한다.

이 파일은 API 키 없이 실행되도록 데모용 규칙 기반 Agent를 씁니다(맨 아래 DEMO 영역).
실제 프로젝트에서는 AGENT_RUNNERS의 함수만 03강 runtime.run_profile() 호출로 바꾸면 됩니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field, ValidationError


# ─────────────────────────────────────────────
# 1. 실행 정책 (계획서 4장 ExecutionPolicy)
# ─────────────────────────────────────────────
class ExecutionPolicy(BaseModel):
    timeout_seconds: float = 30
    max_attempts: int = 2                 # 같은 Provider 재시도 포함 총 시도 수
    allow_provider_failover: bool = True
    max_handoffs: int = 1                 # 무한 Handoff 방지
    retryable_errors: set[str] = {"timeout", "rate_limit", "server_error"}
    max_cost_usd_per_run: float = 0.05    # 문의 1건 비용 한도 (초과 시 상담원 이관)


class AgentError(Exception):
    """Agent 실행 오류. kind로 재시도 가능 여부를 구분한다."""

    def __init__(self, kind: Literal["timeout", "rate_limit", "server_error",
                                     "bad_input", "auth", "contract", "budget"], msg: str = ""):
        super().__init__(f"{kind}: {msg}")
        self.kind = kind


# ─────────────────────────────────────────────
# 1-1. 비용 계산기
#   ⚠ 아래 단가는 "예시값"입니다. 실제 값은 각 Provider 공식 가격 페이지에서
#     확인한 뒤 .env나 설정 파일로 옮기세요. (가격은 자주 바뀝니다)
# ─────────────────────────────────────────────
class ModelPrice(BaseModel):
    model: str
    input_per_1m: float       # USD / 입력 토큰 100만 개
    output_per_1m: float      # USD / 출력 토큰 100만 개


PRICING: dict[str, ModelPrice] = {
    "openai": ModelPrice(model="gpt-4.1-mini", input_per_1m=0.40, output_per_1m=1.60),
    "gemini": ModelPrice(model="gemini-flash", input_per_1m=0.30, output_per_1m=2.50),
    "ollama": ModelPrice(model="llama3.2 (local)", input_per_1m=0.0, output_per_1m=0.0),
}
USD_TO_KRW = 1400             # 화면 표시용 환율 (예시)


def estimate_tokens(text: str) -> int:
    """API가 usage를 주지 않을 때 쓰는 대략적 추정 (한국어는 글자당 토큰이 많음)."""
    return max(1, len(text) // 2)


def call_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICING[provider]
    return (input_tokens * price.input_per_1m + output_tokens * price.output_per_1m) / 1_000_000


# ─────────────────────────────────────────────
# 2. 입출력 계약 (02강 Contract)
# ─────────────────────────────────────────────
Intent = Literal["order", "refund", "technical"]


class TriageDecision(BaseModel):
    intents: list[Intent] = Field(default_factory=list)   # 복합 문의면 여러 개
    order_id: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    reason: str


class SpecialistResult(BaseModel):
    agent_id: str
    summary: str
    facts: dict[str, str] = Field(default_factory=dict)   # Tool에서 확인한 사실만
    handoff_to: str | None = None                         # 다른 Agent로 넘길 때
    handoff_reason: str | None = None
    requires_human_action: bool = False                   # 환불 실행 등 변경 작업


class FinalResponse(BaseModel):
    message: str
    missing_parts: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
# 3. Agent 명세 (Role · Tool Allowlist · 최소 Context · 필수/선택)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    responsibility: str
    allowed_tools: tuple[str, ...]
    context_keys: tuple[str, ...]         # 이 Agent가 받을 최소 Context
    required: bool                        # 필수 실패 → 중단/이관, 선택 실패 → 누락 표시
    providers: tuple[str, ...] = ("openai", "gemini")   # primary, fallback


AGENTS: dict[str, AgentSpec] = {
    "triage_agent": AgentSpec("triage_agent", "문의 유형 분류와 필요 정보 확인",
                              (), ("message",), required=True),
    "order_agent": AgentSpec("order_agent", "주문·배송 상태 조회",
                             ("get_order_status",), ("order_id",), required=True),
    "refund_policy_agent": AgentSpec("refund_policy_agent", "환불 가능 여부와 규정 확인",
                                     ("get_refund_policy",), ("order_id", "order_status"), required=True),
    "technical_support_agent": AgentSpec("technical_support_agent", "기술 문제 안내",
                                         ("search_help_articles",), ("message",), required=False),
    "response_agent": AgentSpec("response_agent", "전문 Agent 결과를 하나의 답변으로 통합",
                                (), ("specialist_summaries", "missing_parts"), required=True),
}

INTENT_TO_AGENT: dict[Intent, str] = {
    "order": "order_agent",
    "refund": "refund_policy_agent",
    "technical": "technical_support_agent",
}

# Handoff Allowlist: 누가 누구에게 넘길 수 있는가
ALLOWED_HANDOFFS: dict[str, set[str]] = {
    "order_agent": {"refund_policy_agent"},
    "technical_support_agent": {"order_agent"},
}


# ─────────────────────────────────────────────
# 4. State · Trace (Audit Trail)
# ─────────────────────────────────────────────
RunStatus = Literal["completed", "partial", "needs_information",
                    "pending_approval", "escalated", "failed"]


@dataclass
class RunState:
    run_id: str
    message: str
    context: dict[str, object] = field(default_factory=dict)
    results: dict[str, SpecialistResult] = field(default_factory=dict)
    failed_optional: list[str] = field(default_factory=list)
    handoffs: int = 0
    trace: list[dict[str, object]] = field(default_factory=list)
    llm_calls: list[dict[str, object]] = field(default_factory=list)   # 비용 기록

    def log(self, event: str, **data: object) -> None:
        self.trace.append({"t": round(time.time(), 3), "event": event, **data})

    @property
    def spent_usd(self) -> float:
        return sum(c["cost_usd"] for c in self.llm_calls)

    def record_call(self, agent: str, provider: str, attempt: int,
                    input_tokens: int, output_tokens: int, ok: bool, error: str | None = None) -> None:
        cost = call_cost(provider, input_tokens, output_tokens)
        self.llm_calls.append({"agent": agent, "provider": provider, "model": PRICING[provider].model,
                               "attempt": attempt, "input_tokens": input_tokens,
                               "output_tokens": output_tokens, "cost_usd": cost,
                               "ok": ok, "error": error})

    def cost_report(self) -> dict[str, object]:
        """문의 1건 비용 요약: 총액, Agent별, Provider별, 실패로 낭비된 비용."""
        by_agent: dict[str, float] = {}
        by_provider: dict[str, float] = {}
        for c in self.llm_calls:
            by_agent[c["agent"]] = by_agent.get(c["agent"], 0) + c["cost_usd"]
            by_provider[c["provider"]] = by_provider.get(c["provider"], 0) + c["cost_usd"]
        wasted = sum(c["cost_usd"] for c in self.llm_calls if not c["ok"])
        total = self.spent_usd
        return {
            "total_usd": round(total, 6),
            "total_krw": round(total * USD_TO_KRW, 2),
            "calls": len(self.llm_calls),
            "failed_calls": sum(1 for c in self.llm_calls if not c["ok"]),
            "wasted_usd": round(wasted, 6),
            "wasted_ratio": round(wasted / total, 3) if total else 0.0,
            "by_agent": {k: round(v, 6) for k, v in by_agent.items()},
            "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
            "input_tokens": sum(c["input_tokens"] for c in self.llm_calls),
            "output_tokens": sum(c["output_tokens"] for c in self.llm_calls),
        }


# ─────────────────────────────────────────────
# 5. 공통 실행 계층: Timeout → Retry → Failover → 계약 검증
# ─────────────────────────────────────────────
Runner = Callable[[str, dict[str, object], str], Awaitable[dict]]
AGENT_RUNNERS: dict[str, Runner] = {}          # agent_id → 실행 함수 (아래 DEMO 또는 실제 LLM)
TOOL_CALLS: list[tuple[str, str]] = []         # (agent_id, tool) 기록 → Allowlist 검사용


def minimal_context(spec: AgentSpec, state: RunState) -> dict[str, object]:
    """전체 State가 아니라 명세에 적힌 키만 골라서 전달한다."""
    return {k: state.context[k] for k in spec.context_keys if k in state.context}


async def run_agent(agent_id: str, schema: type[BaseModel], state: RunState,
                    policy: ExecutionPolicy) -> BaseModel:
    spec = AGENTS[agent_id]
    ctx = minimal_context(spec, state)
    providers = spec.providers if policy.allow_provider_failover else spec.providers[:1]

    last_error: AgentError | None = None
    prompt_text = f"{spec.responsibility}\n{ctx}\n{state.message}"
    for provider in providers:
        for attempt in range(1, policy.max_attempts + 1):
            # 비용 Guard: 한도를 넘으면 더 호출하지 않고 이관
            if state.spent_usd >= policy.max_cost_usd_per_run:
                state.log("budget_exceeded", agent=agent_id, spent_usd=round(state.spent_usd, 6))
                raise AgentError("budget", f"비용 한도 ${policy.max_cost_usd_per_run} 초과")
            state.log("agent_start", agent=agent_id, provider=provider, attempt=attempt,
                      context_keys=list(ctx))
            in_tokens = estimate_tokens(prompt_text)
            try:
                raw = await asyncio.wait_for(AGENT_RUNNERS[agent_id](provider, ctx, state.message),
                                             timeout=policy.timeout_seconds)
                # 실제 LLM이면 응답의 usage 값을 쓰고, 없으면 추정한다
                usage = raw.pop("_usage", None) or {}
                in_tokens = usage.get("input_tokens", in_tokens)
                out_tokens = usage.get("output_tokens", estimate_tokens(str(raw)))
                try:
                    result = schema.model_validate(raw)      # 대체 Provider도 같은 계약 통과 필수
                except ValidationError:
                    state.record_call(agent_id, provider, attempt, in_tokens, out_tokens, ok=False,
                                      error="contract")      # 계약 실패도 토큰은 이미 과금됨
                    raise
                state.record_call(agent_id, provider, attempt, in_tokens, out_tokens, ok=True)
                state.log("agent_done", agent=agent_id, provider=provider,
                          cost_usd=round(state.llm_calls[-1]["cost_usd"], 6))
                return result
            except asyncio.TimeoutError:
                last_error = AgentError("timeout", agent_id)
                state.record_call(agent_id, provider, attempt, in_tokens, 0, ok=False, error="timeout")
            except ValidationError as e:
                last_error = AgentError("contract", str(e.errors()[:1]))
            except AgentError as e:
                last_error = e
                state.record_call(agent_id, provider, attempt, in_tokens, 0, ok=False, error=e.kind)
            state.log("agent_error", agent=agent_id, provider=provider,
                      attempt=attempt, kind=last_error.kind)

            # 입력·인증 오류는 재시도/Failover로 숨기지 않고 즉시 중단 (계획서 4장)
            if last_error.kind in {"bad_input", "auth", "budget"}:
                raise last_error
            if last_error.kind not in policy.retryable_errors | {"contract"}:
                break
        state.log("provider_failover", agent=agent_id, from_provider=provider)
    raise last_error or AgentError("server_error", agent_id)


# ─────────────────────────────────────────────
# 6. Supervisor
# ─────────────────────────────────────────────
class CustomerSupportSupervisor:
    """계획서 흐름을 코드로 고정하고, 각 단계마다 Guard로 검사한다."""

    def __init__(self, policy: ExecutionPolicy | None = None):
        self.policy = policy or ExecutionPolicy()
        self._idempotency: dict[str, dict] = {}   # 같은 요청 중복 실행 방지

    async def handle(self, message: str, request_id: str | None = None) -> dict:
        key = request_id or hashlib.sha256(message.encode()).hexdigest()[:16]
        if key in self._idempotency:                                  # 멱등성
            return {**self._idempotency[key], "idempotent_replay": True}

        state = RunState(run_id=f"run_{uuid.uuid4().hex[:8]}", message=message)
        state.context["message"] = message
        state.log("run_start", request_key=key)
        try:
            outcome = await self._run(state)
        except AgentError as e:
            outcome = self._escalate(state, f"처리 중단: {e}")
        outcome.update(run_id=state.run_id, trace=state.trace,
                       cost=state.cost_report(), llm_calls=state.llm_calls)
        self._idempotency[key] = outcome
        return outcome

    async def _run(self, state: RunState) -> dict:
        p = self.policy

        # ① Triage (필수)
        triage: TriageDecision = await run_agent("triage_agent", TriageDecision, state, p)
        state.log("routing", intents=triage.intents, reason=triage.reason)
        if triage.order_id:
            state.context["order_id"] = triage.order_id

        # ② Guard: 주문 관련인데 주문번호가 없으면 추측하지 않고 되묻기
        needs_order = {"order", "refund"} & set(triage.intents)
        if needs_order and not triage.order_id:
            triage.missing_information.append("주문번호")
        if triage.missing_information or not triage.intents:
            state.log("ask_user", missing=triage.missing_information)
            return {"status": "needs_information",
                    "message": "확인을 위해 다음 정보를 알려주세요: "
                               + ", ".join(triage.missing_information or ["문의 내용"])}

        # ③ Routing + 병렬 실행 (복합 문의면 Parallel, 결과는 Join)
        targets = [INTENT_TO_AGENT[i] for i in dict.fromkeys(triage.intents)]
        # 환불은 주문 상태가 필요하므로 주문 Agent 뒤에 순차 실행 (의존성)
        first_wave = [a for a in targets if a != "refund_policy_agent" or "order_agent" not in targets]
        await self._run_parallel(first_wave, state)
        if "refund_policy_agent" in targets and "refund_policy_agent" not in state.results:
            await self._run_parallel(["refund_policy_agent"], state)

        # ④ Handoff (Allowlist + 최대 횟수 Guard)
        for result in list(state.results.values()):
            target = result.handoff_to
            if not target or target in state.results:
                continue
            if target not in ALLOWED_HANDOFFS.get(result.agent_id, set()):
                state.log("handoff_blocked", source=result.agent_id, target=target)
                continue
            if state.handoffs >= p.max_handoffs:
                state.log("handoff_limit", source=result.agent_id, target=target)
                return self._escalate(state, "Handoff 한도 초과")
            state.handoffs += 1
            state.log("handoff", source=result.agent_id, target=target, reason=result.handoff_reason)
            await self._run_parallel([target], state)

        # ⑤ Join Guard: 필수 Agent 결과가 없으면 최종 통합 중단 → 상담원 이관
        missing_required = [a for a in targets if AGENTS[a].required and a not in state.results]
        if missing_required:
            return self._escalate(state, f"필수 정보 확인 실패: {missing_required}")

        # ⑥ Response Agent (최소 Context: 요약과 누락 목록만)
        state.context["specialist_summaries"] = {k: v.summary for k, v in state.results.items()}
        state.context["missing_parts"] = state.failed_optional
        final: FinalResponse = await run_agent("response_agent", FinalResponse, state, p)

        # ⑦ 최종 응답 검사: 확인되지 않은 약속 금지
        if "환불 완료" in final.message or "환불해 드렸" in final.message:
            state.log("response_blocked", reason="확인되지 않은 환불 약속")
            return self._escalate(state, "최종 응답 정책 위반")

        # ⑧ Human-in-the-loop: 변경 작업은 승인 전 실행 금지
        if any(r.requires_human_action for r in state.results.values()):
            state.log("approval_required", action="refund_request")
            return {"status": "pending_approval", "message": final.message,
                    "approval": "상담원 승인 후 환불 요청서가 처리됩니다."}

        status: RunStatus = "partial" if state.failed_optional else "completed"
        state.log("run_done", status=status)
        return {"status": status, "message": final.message, "missing_parts": state.failed_optional}

    async def _run_parallel(self, agent_ids: list[str], state: RunState) -> None:
        async def one(agent_id: str) -> None:
            try:
                res: SpecialistResult = await run_agent(agent_id, SpecialistResult, state, self.policy)
                self._check_tool_allowlist(agent_id, state)
                state.results[agent_id] = res
                state.context.update(res.facts)                     # 다음 Agent가 쓸 사실
            except AgentError as e:
                if e.kind == "budget":
                    raise                                   # 비용 한도는 전체 실행을 멈춘다
                if AGENTS[agent_id].required:
                    state.log("required_failed", agent=agent_id, kind=e.kind)
                else:
                    state.failed_optional.append(agent_id)
                    state.log("optional_failed", agent=agent_id, kind=e.kind)

        await asyncio.gather(*(one(a) for a in agent_ids))

    @staticmethod
    def _check_tool_allowlist(agent_id: str, state: RunState) -> None:
        used = {tool for a, tool in TOOL_CALLS if a == agent_id}
        illegal = used - set(AGENTS[agent_id].allowed_tools)
        if illegal:
            state.log("tool_blocked", agent=agent_id, tools=sorted(illegal))
            raise AgentError("auth", f"{agent_id} 허용되지 않은 Tool {illegal}")

    @staticmethod
    def _escalate(state: RunState, reason: str) -> dict:
        state.log("escalated", reason=reason)
        return {"status": "escalated", "reason": reason,
                "message": "정확한 확인을 위해 상담원에게 연결해 드릴게요."}


# ─────────────────────────────────────────────
# 7. DEMO: 규칙 기반 Agent (API 키 없이 흐름 확인용)
#    실제 구현에서는 03강 runtime.run_profile()로 교체
# ─────────────────────────────────────────────
FAKE_ORDERS = {"A100": "배송 지연", "A200": "배송 완료"}
FAULTS: dict[str, list[str]] = {}   # 테스트용 장애 주입: agent_id → ["timeout", ...]


def _maybe_fail(agent_id: str) -> None:
    queue = FAULTS.get(agent_id)
    if queue:
        raise AgentError(queue.pop(0), "주입된 장애")


async def demo_triage(provider, ctx, message):
    _maybe_fail("triage_agent")
    intents = [i for i, kws in {"order": ("배송", "택배", "주문"),
                                 "refund": ("환불", "취소", "반품"),
                                 "technical": ("로그인", "오류", "앱")}.items()
               if any(k in message for k in kws)]
    order_id = next((w for w in message.replace(",", " ").split() if w[:1] == "A" and w[1:].isdigit()), None)
    return {"intents": intents, "order_id": order_id, "reason": f"키워드 매칭 {intents}"}


async def demo_order(provider, ctx, message):
    _maybe_fail("order_agent")
    TOOL_CALLS.append(("order_agent", "get_order_status"))
    status = FAKE_ORDERS.get(str(ctx.get("order_id")))
    if status is None:
        raise AgentError("bad_input", "존재하지 않는 주문번호")
    return {"agent_id": "order_agent", "summary": f"주문 {ctx['order_id']}: {status}",
            "facts": {"order_status": status}}


async def demo_refund(provider, ctx, message):
    _maybe_fail("refund_policy_agent")
    TOOL_CALLS.append(("refund_policy_agent", "get_refund_policy"))
    eligible = ctx.get("order_status") == "배송 지연"
    return {"agent_id": "refund_policy_agent",
            "summary": "배송 지연 건은 환불 요청 가능" if eligible else "배송 완료 7일 이내 반품 후 환불",
            "requires_human_action": eligible}


async def demo_technical(provider, ctx, message):
    _maybe_fail("technical_support_agent")
    TOOL_CALLS.append(("technical_support_agent", "search_help_articles"))
    return {"agent_id": "technical_support_agent", "summary": "앱 재설치 후 다시 로그인해 보세요."}


async def demo_response(provider, ctx, message):
    _maybe_fail("response_agent")
    lines = list(ctx["specialist_summaries"].values())
    if ctx.get("missing_parts"):
        lines.append(f"(일부 정보 확인 실패: {ctx['missing_parts']})")
    return {"message": " / ".join(lines), "missing_parts": ctx.get("missing_parts", [])}


def render_cost_table(outcome: dict) -> str:
    """콘솔/Streamlit에 보여줄 호출별 비용 표."""
    rows = ["   | Agent | Provider(모델) | 시도 | 입력 | 출력 | 비용(USD) | 결과 |",
            "   |---|---|---|---|---|---|---|"]
    for c in outcome["llm_calls"]:
        rows.append(f"   | {c['agent']} | {c['provider']}({c['model']}) | {c['attempt']} | "
                    f"{c['input_tokens']} | {c['output_tokens']} | {c['cost_usd']:.7f} | "
                    f"{'성공' if c['ok'] else '실패:' + str(c['error'])} |")
    r = outcome["cost"]
    rows.append(f"   합계 ${r['total_usd']:.6f} / Provider별 {r['by_provider']} / 낭비 ${r['wasted_usd']:.7f}")
    return "\n".join(rows)


AGENT_RUNNERS.update({
    "triage_agent": demo_triage,
    "order_agent": demo_order,
    "refund_policy_agent": demo_refund,
    "technical_support_agent": demo_technical,
    "response_agent": demo_response,
})


async def _demo() -> None:
    cases = [
        ("정상: 배송 문의", "주문 A200 배송 어디쯤인가요?", {}),
        ("병렬+순차: 배송 지연 + 환불", "A100 배송이 늦어요, 환불 가능해요?", {}),
        ("정보 부족: 주문번호 없음", "환불하고 싶어요", {}),
        ("재시도 성공: 주문 조회 timeout 1회", "주문 A200 배송 확인", {"order_agent": ["timeout"]}),
        ("부분 실패: 선택 Agent 실패", "A200 배송이랑 앱 로그인 오류 문의", {"technical_support_agent": ["server_error"] * 4}),
        ("Failover: OpenAI 2회 실패 → Gemini", "주문 A200 배송 확인", {"order_agent": ["server_error"] * 2}),
        ("필수 실패 → 이관", "주문 A200 배송 확인해줘요", {"order_agent": ["server_error"] * 4}),
        ("잘못된 입력 → 즉시 중단", "주문 A999 배송 확인", {}),
    ]
    for title, msg, faults in cases:
        FAULTS.clear(); FAULTS.update({k: list(v) for k, v in faults.items()})
        sup = CustomerSupportSupervisor(ExecutionPolicy(timeout_seconds=2))
        out = await sup.handle(msg)
        c = out["cost"]
        print(f"[{title}] status={out['status']}  호출 {c['calls']}회(실패 {c['failed_calls']})"
              f"  비용 ${c['total_usd']:.6f} (≈{c['total_krw']}원)  낭비 {c['wasted_ratio']:.0%}"
              f"\n   → {out.get('message')}")
        if title.startswith("Failover"):
            print(render_cost_table(out))

    # 비용 한도 Guard: 한도를 아주 낮게 잡으면 중간에 멈추고 이관
    FAULTS.clear()
    sup = CustomerSupportSupervisor(ExecutionPolicy(max_cost_usd_per_run=0.0000005))
    out = await sup.handle("A100 배송이 늦어요, 환불 가능해요?")
    print(f"[비용 한도 초과] status={out['status']} reason={out.get('reason')} 비용 ${out['cost']['total_usd']:.7f}")
    sup = CustomerSupportSupervisor()
    await sup.handle("주문 A200 배송?", request_id="req-1")
    again = await sup.handle("주문 A200 배송?", request_id="req-1")
    print(f"[멱등성: 같은 request_id 재요청] replay={again.get('idempotent_replay')}")


if __name__ == "__main__":
    asyncio.run(_demo())
