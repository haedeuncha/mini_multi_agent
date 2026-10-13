"""
[화면 시나리오]
학습자는 왼쪽 메뉴에서 평가 기준, Evaluator, Feedback, Retry, 복구와 Trace를 차례로
확인합니다. 09에서는 날씨 조회부터 장소·숙소 선택, 승인과 예약까지 한 흐름으로 실행하고,
10에서는 저장된 예약과 같은 run_id의 Trace를 조회합니다.
"""

import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = os.getenv("API_BASE_URL", "http://127.0.0.1:18000")

LAB_GUIDES = {
    "01": ("backend/app/orchestration/engine.py · validate_criteria()", "평가 기준의 가중치 합계가 100인가요?"),
    "02": ("backend/app/agents/evaluator_agent.py · evaluate_draft()", "LLM Feedback과 Python 점수 계산이 분리되어 있나요?"),
    "03": ("backend/app/orchestration/engine.py · run_feedback_workflow()", "평가 실패 후 Feedback이 Reviser에게 전달되나요?"),
    "04": ("backend/app/orchestration/engine.py · execute_with_retry()", "품질 반복과 Provider Retry의 최대 횟수가 다른가요?"),
    "05": ("backend/app/orchestration/failure_policy.py", "일시적 오류와 반복해도 해결되지 않는 오류를 구분하나요?"),
    "06": ("backend/app/routers/evaluation.py · partial_recovery()", "성공한 Writer 결과를 유지하고 실패 부분만 다시 실행하나요?"),
    "07": ("backend/app/observability/tracker.py", "회차별 점수와 Feedback을 같은 run_id로 찾을 수 있나요?"),
    "08": ("backend/app/orchestration/support_flow.py · run_support_evaluation()", "고객지원 답변도 작성→평가→수정 순서로 실행되나요?"),
    "09": ("backend/app/orchestration/travel_booking_flow.py", "장소와 숙소를 선택하고 명시적으로 승인한 뒤에만 예약되나요?"),
    "10": ("backend/app/database/repository.py · list_booking_records()", "예약 결과와 같은 run_id의 Trace를 다시 조회할 수 있나요?"),
    "11": ("backend/app/orchestration/travel_booking_flow.py · confirm_travel_booking()", "앞 단계 결과를 보존하고 실패한 예약 단계만 다시 실행하나요?"),
}

LAB_API_CALLS = {
    "01": [("GET", "/api/criteria", "버튼 · PostgreSQL 평가 기준 조회")],
    "02": [],
    "03": [("POST", "/api/runs", "버튼 · Writer→Evaluator→Reviser 작업 접수"), ("GET", "/api/runs/{run_id}", "1초 간격 Polling · 평가 회차, Feedback, Redis Trace 조회")],
    "04": [],
    "05": [("GET", "/api/failure-cases", "버튼 · 오류 분류와 복구 정책 사례 조회")],
    "06": [("GET", "/api/partial-recovery", "버튼 · 부분 복구 예시 조회")],
    "07": [("POST", "/api/runs", "버튼 · Writer→Evaluator→Reviser 작업 접수"), ("GET", "/api/runs/{run_id}", "1초 간격 Polling · 점수와 Trace 조회")],
    "08": [("POST", "/api/runs/support-evaluation", "버튼 · 고객지원 평가 흐름 실행")],
    "09": [
        ("POST", "/api/travel-booking/plan", "Weather MCP 자동 조회 후 날씨 기반 장소 후보 생성"),
        ("POST", "/api/travel-booking/hotels", "선택 장소 주변 숙소 검색"),
        ("POST", "/api/travel-booking/prepare", "1차 승인 · 전체 예산과 여행 가이드 생성"),
        ("POST", "/api/travel-booking/book", "2차 승인 · 실제 예약 실행과 DB 저장"),
    ],
    "10": [("GET", "/api/bookings?user_id=user-101", "예약 DB 이력 조회"), ("GET", "/api/travel-booking/{run_id}", "추천·예약 Trace 조회")],
    "11": [("POST", "/api/travel-booking/recovery-demo", "날씨 조회부터 선택한 예약 오류와 Retry까지 원클릭 실행"), ("POST", "/api/travel-booking/book", "자동 Retry 실패 시 Booking MCP 단계만 수동 복구")],
}

PRACTICE_FLOWS = {
    "01": ["평가 기준 조회", "필수 여부·가중치 확인", "합계 100 검사", "평가 준비 완료"],
    "02": ["작성된 초안", "Gemma Evaluator", "Feedback 생성", "Python Quality Gate"],
    "03": ["Writer 초안", "Evaluator 평가", "Feedback", "Reviser 수정", "재평가"],
    "04": ["실패 발생", "실패 종류 구분", "최대 횟수 확인", "재시도 또는 종료"],
    "05": ["오류 수신", "Failure Policy 분류", "Retry·중단·사람 확인", "결정 기록"],
    "06": ["Shared State 확인", "성공 결과 보존", "실패 부분만 재실행", "결과 합치기"],
}

LAB_LOCAL_CONTENT = {
    "02": "별도 요청 없음 · Evaluator와 Python Quality Gate의 역할을 설명합니다. 실제 평가는 03·07번에서 실행합니다.",
    "04": "별도 요청 없음 · Provider 재시도와 품질 재평가의 횟수 규칙을 설명합니다. 실제 반복은 03·07번에서 실행합니다.",
}


def api_get(path: str):
    response = requests.get(f"{API}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict, timeout: int = 10):
    """POST 요청을 보냅니다.

    일반 조회·저장은 10초를 사용하고, 여러 LLM을 순서대로 호출하는 화면은 더 긴
    timeout을 명시합니다. timeout은 Backend 실행 시간과 별개의 화면 대기 시간입니다.
    """

    response = requests.post(f"{API}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def api_error_message(error: requests.RequestException) -> str:
    """HTTP 상태 코드 대신 Backend가 보낸 학습용 오류 설명을 보여 줍니다."""

    response = getattr(error, "response", None)
    if response is not None:
        try:
            detail = response.json().get("detail")
            if detail:
                return str(detail)
        except (ValueError, AttributeError):
            pass
    return str(error)


def show_lab_header(lab_id: str, labs: dict) -> None:
    lab = labs[lab_id]
    code_path, analysis_question = LAB_GUIDES[lab_id]
    st.title(f"{lab_id} · {lab['title']}")
    st.caption("이 화면의 Backend 요청")
    if LAB_API_CALLS[lab_id]:
        for method, endpoint, action in LAB_API_CALLS[lab_id]:
            st.code(f"{method} {API}{endpoint}", language="text")
            st.caption(action)
    else:
        st.info(LAB_LOCAL_CONTENT[lab_id])
    st.info(f"생각할 질문 · {lab['question']}")
    st.success(f"핵심 답변 · {lab['answer_summary']}")
    with st.expander("상세 답변 보기"):
        for detail in lab["answer_details"]:
            st.write(f"- {detail}")
    left, right = st.columns(2)
    left.metric("실제 LLM", "사용" if lab["real_llm"] else "미사용")
    right.metric("예상 호출", lab["expected_calls"])
    with st.expander("실행 후 먼저 읽을 코드"):
        st.code(code_path, language="text")
    with st.expander("실행 결과 분석 질문"):
        st.write(f"- {analysis_question}")


def render_practice_flow(lab_id: str) -> None:
    """01~06에서 학생이 먼저 전체 실행 순서를 볼 수 있게 합니다."""

    nodes = PRACTICE_FLOWS[lab_id]
    diagram = "digraph Flow { rankdir=LR; node [shape=box, style=rounded]; "
    diagram += " ".join(f'n{index} [label="{label}"];' for index, label in enumerate(nodes))
    diagram += " ".join(f"n{index} -> n{index + 1};" for index in range(len(nodes) - 1)) + " }"
    st.subheader("실습 흐름")
    st.graphviz_chart(diagram, width="stretch")


def render_feedback_quality_criteria() -> None:
    """03에서 사용하는 문서 품질 기준과 Python 판정 코드를 쉽게 설명합니다."""

    st.subheader("문서 품질을 판단하는 기본 평가 기준")
    st.write(
        "03은 아래 네 가지 기준으로 여행 안내문을 검사합니다. 안내문에 확인할 표현이 들어 있으면 "
        "해당 점수를 얻습니다. 총점이 80점 이상이고 반드시 필요한 세 항목이 모두 있어야 통과합니다."
    )
    st.dataframe(
        [
            {"확인할 내용": "사용자가 승인하기 전에는 결제하지 않는다고 안내했는가?", "안내문에 들어갈 표현": "승인 전에는 결제를 실행하지 않습니다.", "점수": 40, "반드시 필요": "예"},
            {"확인할 내용": "예산이 확정 금액이 아니라 예상 금액이라고 안내했는가?", "안내문에 들어갈 표현": "예상 금액", "점수": 20, "반드시 필요": "예"},
            {"확인할 내용": "외부 정보가 나중에 달라질 수 있다고 안내했는가?", "안내문에 들어갈 표현": "변동될 수 있습니다", "점수": 20, "반드시 필요": "예"},
            {"확인할 내용": "사용자가 다음에 무엇을 확인해야 하는지 알려 주었는가?", "안내문에 들어갈 표현": "확인해 주세요", "점수": 20, "반드시 필요": "아니요"},
        ],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "예: 필수 기준 세 개를 모두 만족하면 80점이므로 통과합니다. "
        "점수가 80점이어도 반드시 필요한 내용 하나가 빠졌다면 통과하지 못합니다."
    )

    with st.expander("평가 기준과 판정 코드 읽어 보기"):
        st.caption("평가 기준 Seed · sql/001_evaluation_schema.sql")
        st.code(
            '''('approval_boundary', '승인 전 결제 금지 안내',
   '승인 전에는 결제를 실행하지 않습니다.', 40, TRUE),
('budget_notice', '예산은 예상 금액임을 안내',
   '예상 금액', 20, TRUE),
('source_notice', '외부 정보는 변동될 수 있음을 안내',
   '변동될 수 있습니다', 20, TRUE),
('next_action', '사용자가 다음 행동을 이해할 수 있음',
   '확인해 주세요', 20, FALSE)''',
            language="sql",
        )
        st.caption("Python 자동 검사 · backend/app/agents/evaluator_agent.py")
        st.code(
            '''# 문서에 필수 문구가 실제로 있는 기준만 통과 처리합니다.
passed_keys = [
    row["criterion_key"]
    for row in criteria
    if row["required_text"] in draft.content
]

# 통과한 기준의 점수를 합산합니다.
score = sum(
    row["weight"]
    for row in criteria
    if row["criterion_key"] in passed_keys
)

# 80점 이상이고 모든 필수 기준을 만족해야 최종 통과합니다.
mandatory_keys = {row["criterion_key"] for row in criteria if row["mandatory"]}
passed = score >= 80 and mandatory_keys.issubset(set(passed_keys))''',
            language="python",
        )
        st.write(
            "Gemma Evaluator는 문서를 읽고 수정 Feedback을 작성합니다. "
            "최종 점수와 통과 여부는 위 Python 코드가 같은 기준으로 다시 확인합니다."
        )


def render_support_quality_criteria() -> None:
    """08의 고객지원 답변 기준과 Python 판정 코드를 설명합니다."""

    st.subheader("고객지원 답변의 기본 평가 기준")
    st.write(
        "08은 업무가 바뀌면 평가 기준도 바뀌어야 한다는 것을 보여 줍니다. "
        "두 가지 안내가 모두 있어야 100점으로 통과합니다."
    )
    st.dataframe(
        [
            {"확인할 내용": "고객이 직접 따라 할 확인 방법을 안내했는가?", "답변에 들어갈 표현": "확인 절차", "점수": 50, "반드시 필요": "예"},
            {"확인할 내용": "AI가 실제로 계정을 변경했다고 오해하지 않도록 안내했는가?", "답변에 들어갈 표현": "실제 변경을 완료하지 않았습니다", "점수": 50, "반드시 필요": "예"},
        ],
        width="stretch",
        hide_index=True,
    )
    st.info("한 기준만 만족하면 50점으로 실패하고, 두 기준을 모두 만족해야 100점으로 통과합니다.")

    with st.expander("고객지원 평가 기준과 판정 코드 읽어 보기"):
        st.caption("기준 정의 · backend/app/orchestration/support_flow.py")
        st.code(
            '''SUPPORT_CRITERIA = [
    {
        "criterion_key": "checks",
        "required_text": "확인 절차",
        "weight": 50,
        "mandatory": True,
    },
    {
        "criterion_key": "no_false_claim",
        "required_text": "실제 변경을 완료하지 않았습니다",
        "weight": 50,
        "mandatory": True,
    },
]''',
            language="python",
        )
        st.caption("Python 자동 검사 · evaluate_support_text()")
        st.code(
            '''passed = [
    item["criterion_key"]
    for item in SUPPORT_CRITERIA
    if item["required_text"] in draft.content
]
score = sum(
    item["weight"]
    for item in SUPPORT_CRITERIA
    if item["criterion_key"] in passed
)
failed = [
    item["criterion_key"]
    for item in SUPPORT_CRITERIA
    if item["criterion_key"] not in passed
]

# 두 기준이 모두 있어야 최종 통과합니다.
passed = score == 100 and not failed''',
            language="python",
        )
        st.write(
            "OpenAI Evaluator는 부족한 부분과 수정 방법을 Feedback으로 만듭니다. "
            "Python은 답변에 두 가지 안내가 실제로 있는지 확인해 최종 점수를 결정합니다."
        )


def render_travel_quality_criteria() -> None:
    """09·11의 추천과 여행 가이드에 적용되는 평가 기준을 설명합니다."""

    st.subheader("여행 예약 흐름의 기본 평가 기준")
    st.write("09와 11은 장소, 숙소, OpenAI 여행 가이드를 다음 기준으로 각각 검사합니다.")
    st.dataframe(
        [
            {"평가 대상": "장소 추천", "쉽게 확인할 내용": "비가 오면 실내 장소, 맑으면 야외 장소가 첫 번째로 추천되었는가? 날씨가 애매하면 날씨 영향을 적게 받는 장소가 먼저 나오는가?", "점수": "맞으면 100점 · 아니면 60점"},
            {"평가 대상": "숙소 추천", "쉽게 확인할 내용": "모든 숙소에 선택한 장소에서 이동하는 시간이 표시되어 있는가?", "점수": "50점"},
            {"평가 대상": "숙소 추천", "쉽게 확인할 내용": "모든 숙소에 1박 가격이 표시되어 있는가?", "점수": "50점"},
            {"평가 대상": "여행 가이드", "쉽게 확인할 내용": "사용자가 선택한 장소 이름이 들어 있는가?", "점수": "20점"},
            {"평가 대상": "여행 가이드", "쉽게 확인할 내용": "사용자가 선택한 숙소 이름이 들어 있는가?", "점수": "20점"},
            {"평가 대상": "여행 가이드", "쉽게 확인할 내용": "안내된 비용이 확정 금액이 아니라 예상 금액임을 알려 주는가?", "점수": "20점"},
            {"평가 대상": "여행 가이드", "쉽게 확인할 내용": "예약 전에 사용자의 최종 승인이 필요하다고 알려 주는가?", "점수": "20점"},
            {"평가 대상": "여행 가이드", "쉽게 확인할 내용": "여행 날짜 수만큼 일정이 작성되어 있는가?", "점수": "20점"},
        ],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "숙소와 여행 가이드는 모든 내용을 만족해야 통과합니다. 여행 가이드에 빠진 내용이 있으면 "
        "무엇이 빠졌는지 OpenAI에 알려 주고 한 번만 다시 작성합니다."
    )

    with st.expander("여행 평가 코드 읽어 보기"):
        st.caption("장소·숙소 평가 · backend/app/orchestration/travel_booking_flow.py")
        st.code(
            '''# 비가 오면 실내, 맑으면 야외, 그 밖에는 날씨 영향을 적게 받는 장소인지 확인합니다.
rainy = "비" in weather or "rain" in weather.lower()
sunny = "맑" in weather or "sun" in weather.lower()
allowed = {"rainy", "any"} if rainy else {"sunny", "any"} if sunny else {"any"}
weather_matched = top_place["weather_fit"] in allowed
place_score = 100 if weather_matched else 60

# 모든 숙소에 거리와 가격 정보가 있는지 확인합니다.
has_distance = all("distance_minutes" in hotel for hotel in hotels)
has_price = all("nightly_price" in hotel for hotel in hotels)
hotel_score = 50 * int(has_distance) + 50 * int(has_price)
hotel_passed = hotel_score == 100''',
            language="python",
        )
        st.caption("여행 가이드 평가 · backend/app/agents/travel_guide_agent.py")
        st.code(
            '''checks = {
    "selected_place": place["name"] in combined,
    "selected_hotel": hotel["name"] in combined,
    "estimated_budget_notice": "예상 금액" in combined,
    "final_approval_notice": "최종 승인" in combined,
    "schedule_days": len(guide.schedule) >= nights + 1,
}
failed = [name for name, passed in checks.items() if not passed]
score = round(100 * sum(checks.values()) / len(checks))
passed = not failed''',
            language="python",
        )


def render_intro_practice(lab_id: str, labs: dict) -> None:
    """01·02·04·05·06을 버튼으로 실행하고 결과를 읽는 간단한 실습 화면입니다."""

    show_lab_header(lab_id, labs)
    render_practice_flow(lab_id)
    result_key = f"intro-practice-result-{lab_id}"

    if lab_id == "01":
        st.write("DB에 저장된 평가 기준을 직접 불러와 필수 기준과 가중치 합계를 확인합니다.")
        if st.button("평가 기준 불러오기", type="primary", width="stretch", key="run-lab-01"):
            try:
                criteria = api_get("/api/criteria")
                st.session_state[result_key] = {
                    "criteria": criteria,
                    "weight_total": sum(int(item["weight"]) for item in criteria if item.get("active", True)),
                    "mandatory_count": sum(1 for item in criteria if item.get("mandatory")),
                }
            except requests.RequestException as error:
                st.error(f"평가 기준 조회 실패: {error}")
    elif lab_id == "02":
        example = st.radio("평가 예시", ["필수 문구가 모두 있는 초안", "필수 문구가 빠진 초안"], horizontal=True)
        if st.button("Evaluator와 Quality Gate 역할 비교", type="primary", width="stretch", key="run-lab-02"):
            passed = example == "필수 문구가 모두 있는 초안"
            st.session_state[result_key] = {
                "입력": example,
                "Gemma Evaluator": "로컬 모델이 내용을 읽고 구체적인 수정 Feedback을 작성합니다.",
                "Python Quality Gate": "필수 문구 포함 여부와 기준 점수를 코드로 다시 확인합니다.",
                "최종 판정": "통과" if passed else "실패 · Feedback을 Reviser에게 전달",
            }
    elif lab_id == "04":
        failure_kind = st.radio("확인할 실패", ["품질 기준 실패", "일시적 Provider 오류", "권한·계약 오류"], horizontal=True)
        if st.button("최대 반복 횟수 확인", type="primary", width="stretch", key="run-lab-04"):
            policies = {
                "품질 기준 실패": {"처리": "Feedback 후 Reviser 실행", "최대": "평가 5회", "이유": "결과 내용을 개선하는 반복"},
                "일시적 Provider 오류": {"처리": "같은 Provider 호출 재시도", "최대": "호출별 2회", "이유": "잠시 후 성공할 수 있는 기술 오류"},
                "권한·계약 오류": {"처리": "즉시 중단", "최대": "0회", "이유": "반복해도 해결되지 않는 오류"},
            }
            st.session_state[result_key] = {"실패 종류": failure_kind, **policies[failure_kind]}
    elif lab_id == "05":
        if st.button("오류별 복구 결정 불러오기", type="primary", width="stretch", key="run-lab-05"):
            try:
                st.session_state[result_key] = api_get("/api/failure-cases")
            except requests.RequestException as error:
                st.error(f"Failure Policy 조회 실패: {error}")
    else:
        if st.button("부분 복구 예시 실행", type="primary", width="stretch", key="run-lab-06"):
            try:
                st.session_state[result_key] = api_get("/api/partial-recovery")
            except requests.RequestException as error:
                st.error(f"부분 복구 조회 실패: {error}")

    result = st.session_state.get(result_key)
    if result is None:
        st.info("값을 선택하거나 실행 버튼을 눌러 결과를 확인해 보세요.")
        return

    st.subheader("실행 결과")
    if lab_id == "01":
        left, right = st.columns(2)
        left.metric("활성 기준 가중치 합계", result["weight_total"])
        right.metric("필수 기준 수", result["mandatory_count"])
        if result["weight_total"] == 100:
            st.success("가중치 합계가 100이므로 평가를 시작할 수 있습니다.")
        else:
            st.warning("가중치 합계를 100으로 수정해야 합니다.")
        st.dataframe(result["criteria"], width="stretch", hide_index=True)
    elif lab_id == "05":
        st.dataframe(result, width="stretch", hide_index=True)
    elif lab_id == "06":
        st.success(f"보존할 성공 결과: {', '.join(result['kept_results'])}")
        st.warning(f"다시 실행할 부분: {result['retry_target']}")
        st.json(result)
    else:
        st.json(result)


def poll_run(run_id: str) -> dict:
    progress_area = st.progress(0)
    status_area = st.empty()
    metric_area = st.empty()
    trace_area = st.empty()
    latest: dict = {}

    for _ in range(600):
        latest = api_get(f"/api/runs/{run_id}")
        progress_area.progress(int(latest.get("progress", 0)))
        status_area.info(
            f"현재 Agent: {latest.get('current_actor')} · 단계: {latest.get('current_stage')} · "
            f"회차: {latest.get('current_round') or '-'} · {latest.get('message')}"
        )
        events = latest.get("events", [])
        evaluation_events = [event for event in events if event.get("stage") == "evaluate"]
        if evaluation_events:
            last_evaluation = evaluation_events[-1]
            metric_area.metric("최근 평가 점수", last_evaluation.get("details", {}).get("score", 0))
        trace_area.dataframe(events, width="stretch", hide_index=True)
        if latest.get("status") in {"completed", "quality_failed", "failed"}:
            return latest
        time.sleep(1)
    raise TimeoutError("10분 안에 실행이 끝나지 않았습니다.")


def render_travel_booking(labs: dict) -> None:
    show_lab_header("09", labs)
    st.subheader("전체 실행 흐름")
    st.graphviz_chart(
        r'''
        digraph TravelBooking {
            rankdir=LR;
            node [shape=box, style=rounded];
            start [label="사용자 입력"];
            recommend [label="날씨 → 장소 → 숙소"];
            approval1 [label="1차 승인", shape=diamond];
            plan [label="Budget Agent 계산\nOpenAI Guide 작성\nPython Gate 평가"];
            approval2 [label="2차 승인", shape=diamond];
            booking [label="Booking MCP\n예약 · DB 저장"];
            history [label="예약 · Trace 조회"];
            start -> recommend -> approval1 -> plan -> approval2 -> booking -> history;
        }
        ''',
        width="stretch",
    )
    st.caption("1차 승인은 예산과 가이드 생성만 허용하고, 2차 승인 후에만 실제 예약과 DB 저장을 실행합니다.")
    st.write("실제 날씨 조회부터 장소 선택, 주변 숙소 검색, 예약 내용 확인과 승인까지 하나의 run_id로 이어집니다.")
    st.info("Trace에는 실행 흐름만 남기고 API Key, 비밀번호, 인증 Token, 전체 Prompt 원문, 불필요한 개인정보는 남기지 않습니다.")
    render_travel_quality_criteria()
    st.info("통합 예약은 Weather MCP, Hotel MCP, Booking MCP 서버에 연결합니다. 연결 오류가 나면 아래 명령으로 해당 서버를 시작하세요.")
    st.code("""python .\\mcp_weather_server\\main.py
python .\\mcp_hotel_server\\main.py
python .\\mcp_booking_server\\main.py""", language="powershell")

    user_id = st.text_input("사용자 ID", "user-101", key="travel-user-id")
    destination = st.selectbox("목적지", ["부산"], help="현재 시드는 부산만 준비되어 있습니다.")
    preferences_text = st.text_input("취향", "실내,맛집")

    if st.button("1. 여행 시작 · 날씨 자동 조회와 장소 추천", type="primary", width="stretch"):
        preferences = [item.strip() for item in preferences_text.split(",") if item.strip()]
        try:
            st.session_state["travel-plan-result"] = api_post(
                "/api/travel-booking/plan",
                {"user_id": user_id, "destination": destination, "preferences": preferences},
            )
            st.session_state.pop("hotel-search-result", None)
            st.session_state.pop("prepared-plan", None)
            st.session_state.pop("booking-result", None)
        except requests.RequestException as error:
            st.error(f"여행 추천 실행 실패: {error}")

    result = st.session_state.get("travel-plan-result")
    if not result:
        st.info("사용자 ID와 지역을 확인하고 여행 시작 버튼을 눌러 주세요.")
        return

    st.success(f"run_id: {result['run_id']}")
    st.subheader("자동 조회한 실제 날씨")
    st.json(result.get("actual_weather", {}))
    st.subheader("장소 후보")
    st.dataframe(result["place_options"], width="stretch", hide_index=True)
    st.subheader("장소 추천 평가")
    st.json(result["place_evaluation"])
    place_names = {f"{place['name']} · 추천점수 {place['score']}": place["place_id"] for place in result["place_options"]}
    selected_place_label = st.selectbox("3. 숙소를 검색할 장소", list(place_names.keys()))
    if st.button("선택한 장소 주변 숙소 검색", type="primary", width="stretch"):
        try:
            st.session_state["hotel-search-result"] = api_post(
                "/api/travel-booking/hotels",
                {"run_id": result["run_id"], "user_id": result["user_id"], "place_id": place_names[selected_place_label]},
            )
            st.session_state.pop("prepared-plan", None)
            st.session_state.pop("booking-result", None)
        except requests.RequestException as error:
            st.error(f"숙소 검색 실패: {api_error_message(error)}")

    hotel_result = st.session_state.get("hotel-search-result")
    if not hotel_result:
        st.info("장소를 선택하고 주변 숙소를 검색해 주세요.")
        return
    st.subheader("선택 장소 주변 숙소")
    st.dataframe(hotel_result.get("hotel_options", []), width="stretch", hide_index=True)
    st.subheader("숙소 추천 평가")
    st.json(hotel_result.get("hotel_evaluation", {}))

    hotels = hotel_result.get("hotel_options", [])
    if not hotels:
        st.error("예약 가능한 숙소가 없습니다. Hotel MCP 서버를 확인하고 다시 조회하세요.")
        return
    hotel_names = {f"{hotel['name']} · {hotel['near_place']} · {hotel['nightly_price']}원": hotel["hotel_id"] for hotel in hotels}
    selected_label = st.selectbox("4. 예약할 숙소", list(hotel_names.keys()))
    selected_hotel = next(hotel for hotel in hotels if hotel["hotel_id"] == hotel_names[selected_label])
    check_in = st.date_input("체크인", value=date.today() + timedelta(days=1), key="booking-check-in")
    check_out = st.date_input("체크아웃", value=date.today() + timedelta(days=2), key="booking-check-out")
    guest_count = st.number_input("인원", min_value=1, max_value=10, value=2, step=1, key="booking-guests")
    nights = max((check_out - check_in).days, 0)
    estimated_lodging = int(selected_hotel["nightly_price"]) * nights
    st.subheader("5. 1차 승인 · 여행 조건 확인")
    st.json({"숙소": selected_hotel["name"], "장소": selected_hotel["near_place"], "체크인": check_in.isoformat(), "체크아웃": check_out.isoformat(), "인원": int(guest_count), "숙박일": nights, "예상 숙박비": estimated_lodging})
    plan_approved = st.checkbox("이 조건으로 전체 예산과 여행 가이드를 생성하는 데 동의합니다.", key="plan-approved")

    if st.button("6. 1차 승인 후 예산·가이드 만들기", type="primary", width="stretch", disabled=not plan_approved or nights < 1):
        try:
            with st.spinner("Budget Agent 계산 → OpenAI 여행 가이드 작성 → Python 품질 검사를 실행하고 있습니다..."):
                st.session_state["prepared-plan"] = api_post(
                    "/api/travel-booking/prepare",
                    {
                        "run_id": hotel_result["run_id"],
                        "user_id": hotel_result["user_id"],
                        "hotel_id": hotel_names[selected_label],
                        "check_in": check_in.isoformat(),
                        "check_out": check_out.isoformat(),
                        "guest_count": int(guest_count),
                        "approved": plan_approved,
                    },
                    timeout=180,
                )
        except requests.RequestException as error:
            st.error(f"여행 계획 생성 실패: {error}")

    prepared = st.session_state.get("prepared-plan")
    if not prepared:
        st.info("1차 승인 후 전체 예산과 여행 가이드가 만들어집니다. 아직 예약되지는 않습니다.")
        return

    if prepared.get("status") == "plan_failed":
        st.error("OpenAI가 한 번 수정한 뒤에도 여행 가이드가 품질 기준을 통과하지 못했습니다. 실제 예약은 실행할 수 없습니다.")
        st.dataframe(prepared.get("guide_evaluations", []), width="stretch", hide_index=True)
        with st.expander("실패 Trace 보기"):
            st.dataframe(prepared.get("events", []), width="stretch", hide_index=True)
        return

    st.subheader("7. 전체 예상 예산")
    budget = prepared["budget"]
    st.metric("전체 예상 금액", f"{int(budget['total']):,}원")
    st.json(budget)
    st.subheader("8. 여행 가이드")
    st.write(prepared["travel_guide"]["title"])
    st.info(prepared["travel_guide"]["weather_tip"])
    st.dataframe(prepared["travel_guide"]["schedule"], width="stretch", hide_index=True)
    st.subheader("여행 가이드 품질 평가")
    st.dataframe(prepared.get("guide_evaluations", []), width="stretch", hide_index=True)
    st.warning("현재는 계획만 생성된 상태입니다. 아래 2차 승인을 해야 실제 숙소 예약과 DB 저장이 실행됩니다.")
    booking_approved = st.checkbox("전체 예산과 여행 가이드를 확인했으며 실제 숙소 예약을 승인합니다.", key="booking-approved")

    if st.button("9. 2차 승인 후 실제 예약", type="primary", width="stretch", disabled=not booking_approved):
        try:
            st.session_state["booking-result"] = api_post(
                "/api/travel-booking/book",
                {"run_id": prepared["run_id"], "user_id": prepared["user_id"], "approved": booking_approved},
            )
        except requests.RequestException as error:
            st.error(f"예약 실행 실패: {error}")

    if "booking-result" in st.session_state:
        booking_result = st.session_state["booking-result"]
        if booking_result.get("status") == "booked":
            st.success("예약 MCP 서버가 예약을 완료했습니다.")
        else:
            st.error(booking_result.get("error", "예약 MCP 서버 호출 또는 저장에 실패했습니다."))
        st.json(booking_result)
        st.subheader("10. 두 번의 승인이 포함된 전체 Trace")
        st.dataframe(booking_result.get("events", []), width="stretch", hide_index=True)


def render_booking_history(labs: dict) -> None:
    show_lab_header("10", labs)
    user_id = st.text_input("조회할 사용자 ID", "user-101")
    if st.button("예약 이력 조회", type="primary", width="stretch"):
        try:
            st.session_state["booking-history"] = api_get(f"/api/bookings?user_id={user_id}")
        except requests.RequestException as error:
            st.error(f"예약 이력 조회 실패: {error}")

    if "booking-history" in st.session_state:
        st.dataframe(st.session_state["booking-history"], width="stretch", hide_index=True)

    booking_result = st.session_state.get("booking-result")
    run_id = booking_result.get("run_id") if booking_result else None
    if run_id:
        st.subheader("09에서 완료한 예약의 전체 Trace")
        try:
            state = api_get(f"/api/travel-booking/{run_id}")
            st.dataframe(state.get("events", []), width="stretch", hide_index=True)
        except requests.RequestException as error:
            st.error(f"Trace 조회 실패: {error}")


def render_booking_recovery(labs: dict) -> None:
    """11: 오류 위치를 먼저 선택하고 전체 예약·복구를 한 번에 실행합니다."""

    show_lab_header("11", labs)
    st.subheader("전체 실행 흐름")
    st.graphviz_chart(
        r'''
        digraph BookingRecovery {
            rankdir=LR;
            node [shape=box, style=rounded];
            start [label="장애 시나리오 선택\n전체 흐름 시작"];
            plan [label="날씨·추천·예산·가이드\n자동 승인"];
            booking [label="Booking MCP", shape=diamond];
            retry [label="자동 Retry\n최대 2회"];
            failed [label="booking_failed"];
            manual [label="예약 단계만\n수동 복구"];
            booked [label="booked\nDB 1건 저장"];
            start -> plan -> booking;
            booking -> booked [label="성공"];
            booking -> retry [label="일시적 오류"];
            retry -> booked [label="복구"];
            retry -> failed [label="2회 실패"];
            failed -> manual -> booked;
        }
        ''',
        width="stretch",
    )
    st.info("11은 복구 학습에 집중하기 위해 장소·숙소는 최고 점수 후보를 자동 선택하고, 동의 후 1차·2차 승인을 수업용으로 자동 처리합니다.")
    render_travel_quality_criteria()

    scenario_labels = {
        "정상 예약": "normal",
        "첫 호출만 실패 → 자동 Retry 성공": "fail_once",
        "두 번 모두 실패 → 수동 복구 대기": "fail_twice",
    }
    user_id = st.text_input("사용자 ID", "user-110", key="recovery-user-id")
    destination = st.selectbox("지역", ["부산"], key="recovery-destination")
    selected = st.radio("예약 장애 시나리오", list(scenario_labels), horizontal=True)
    approved = st.checkbox("복구 실습을 위해 1차·2차 승인을 자동 처리하는 데 동의합니다.", key="recovery-approved")
    if st.button("전체 예약·복구 시나리오 실행", type="primary", width="stretch", disabled=not approved):
        try:
            with st.spinner("날씨 조회 → 장소·숙소 선택 → 예산·가이드 → 예약 Retry를 한 번에 실행하고 있습니다..."):
                st.session_state["recovery-result"] = api_post(
                    "/api/travel-booking/recovery-demo",
                    {"user_id": user_id, "destination": destination, "failure_scenario": scenario_labels[selected], "auto_approve": True},
                    timeout=240,
                )
        except requests.RequestException as error:
            st.error(f"예약 복구 실행 실패: {api_error_message(error)}")

    result = st.session_state.get("recovery-result")
    if not result:
        return
    if result.get("status") == "booked":
        st.success("전체 흐름이 완료됐으며 예약은 DB에 한 번만 저장되었습니다.")
    else:
        st.error("자동 Retry 2회가 모두 실패했습니다. 앞 단계 결과는 그대로 보존되어 있습니다.")
        st.write("다시 실행할 단계:", result.get("retry_target"))
        st.write("보존된 결과:", result.get("preserved_results", []))
        if st.button("Booking MCP 단계만 다시 실행", type="primary", width="stretch"):
            try:
                recovered = api_post(
                    "/api/travel-booking/book",
                    {"run_id": result["run_id"], "user_id": result["user_id"], "approved": True, "failure_scenario": "normal"},
                    timeout=30,
                )
                st.session_state["recovery-result"] = recovered
                st.rerun()
            except requests.RequestException as error:
                st.error(f"수동 복구 실패: {api_error_message(error)}")
    st.subheader("Retry와 부분 복구 Trace")
    st.dataframe(result.get("events", []), width="stretch", hide_index=True)


st.set_page_config(page_title="Mini Multi-Agent 07", page_icon="📊", layout="wide")
st.sidebar.title("📊 Mini Multi-Agent 07")
MENU = [
    "과정 안내",
    "실행 환경 점검",
    "01 · Evaluation Criteria",
    "02 · Evaluator Agent",
    "03 · Feedback Loop",
    "04 · Bounded Retry",
    "05 · Failure Policy",
    "06 · Partial Recovery",
    "07 · Quality Trace",
    "08 · 다른 업무에 평가 적용",
    "09 · 통합 여행 예약",
    "10 · 예약 조회와 Trace",
    "11 · 예약 실패와 부분 복구",
    "Agent Registry · YAML",
    "PostgreSQL 실행 이력",
    "Provider 상태",
]
menu = st.sidebar.radio("학습 메뉴", MENU)

try:
    labs = api_get("/api/labs")
except requests.RequestException as error:
    st.error(f"Backend 연결 실패: {error}")
    st.stop()

if menu == "과정 안내":
    st.title("결과 생성에서 평가·개선·복구·추적까지")
    st.caption("이 화면의 Backend 요청")
    st.code(f"GET {API}/api/labs", language="text")
    st.caption("과정 01~11의 설명 조회")
    st.code("Writer → Evaluator ─ 통과 → 완료\n                    └ 실패 → Feedback → Reviser → 재평가 (최대 5회)")
    st.code("여행 요청 → 장소 추천 평가 → 숙소 후보 평가 → 사용자 선택 → 예약 MCP 서버 → DB 저장 → 예약 조회")
    for lab_id, lab in labs.items():
        with st.expander(f"{lab_id} · {lab['title']} — {lab['question']}"):
            st.success(lab["answer_summary"])
            for detail in lab["answer_details"]:
                st.write(f"- {detail}")
            st.caption(f"예상 LLM 호출: {lab['expected_calls']}")
    st.info("품질 개선 반복과 Provider 오류 Retry는 서로 다른 흐름입니다.")
elif menu in {"실행 환경 점검", "Provider 상태"}:
    st.title(menu)
    st.caption("이 화면의 Backend 요청")
    st.code(f"GET {API}/api/providers", language="text")
    st.caption("Provider 설정과 상태 조회")
    st.dataframe([{"provider": name, **value} for name, value in api_get("/api/providers").items()], width="stretch", hide_index=True)
elif menu == "01 · Evaluation Criteria":
    render_intro_practice("01", labs)
elif menu == "02 · Evaluator Agent":
    render_intro_practice("02", labs)
elif menu == "04 · Bounded Retry":
    render_intro_practice("04", labs)
elif menu == "05 · Failure Policy":
    render_intro_practice("05", labs)
elif menu == "06 · Partial Recovery":
    render_intro_practice("06", labs)
elif menu == "Agent Registry · YAML":
    st.title(menu)
    st.caption("이 화면의 Backend 요청")
    st.code(f"GET {API}/api/registry", language="text")
    st.caption("Agent와 평가 실행 정책 조회")
    st.write("읽기 쉬운 Agent 정의는 Python, 반복 횟수와 Provider 실행 정책은 YAML입니다.")
    st.json(api_get("/api/registry"))
elif menu == "PostgreSQL 실행 이력":
    st.title(menu)
    st.caption("이 화면의 Backend 요청")
    st.code(f"GET {API}/api/history", language="text")
    st.caption("완료된 실행 조회")
    st.code(f"GET {API}/api/history/{{run_id}}/rounds", language="text")
    st.caption("선택한 실행의 평가 회차 조회")
    try:
        history = api_get("/api/history")
        st.dataframe(history, width="stretch", hide_index=True)
        if history:
            selected_run = st.selectbox("평가 회차를 볼 run_id", [row["run_id"] for row in history])
            st.dataframe(api_get(f"/api/history/{selected_run}/rounds"), width="stretch", hide_index=True)
    except requests.RequestException as error:
        st.error(f"실행 이력 조회 실패: {error}")
elif menu in {"03 · Feedback Loop", "07 · Quality Trace"}:
    lab_id = "03" if menu.startswith("03") else "07"
    show_lab_header(lab_id, labs)
    if lab_id == "03":
        render_practice_flow("03")
        render_feedback_quality_criteria()
    else:
        render_feedback_quality_criteria()
        st.subheader("Trace를 읽는 방법")
        st.graphviz_chart(
            r'''
            digraph QualityTrace {
                rankdir=LR;
                node [shape=box, style=rounded];
                write [label="OpenAI 초안"];
                evaluate [label="Gemma 평가", shape=diamond];
                retry [label="같은 Gemma 호출 재시도\n최대 2회"];
                revise [label="OpenAI Reviser 수정"];
                complete [label="completed"];
                quality_failed [label="quality_failed\n최대 5회 후 종료"];
                failed [label="failed\nProvider 복구 실패"];
                write -> evaluate;
                evaluate -> retry [label="일시적 호출 오류"];
                retry -> evaluate [label="2번째 호출"];
                retry -> failed [label="2회 모두 실패"];
                evaluate -> complete [label="품질 통과"];
                evaluate -> revise [label="품질 미통과"];
                revise -> evaluate [label="다음 평가 회차"];
                evaluate -> quality_failed [label="5회까지 미통과"];
            }
            ''',
            width="stretch",
        )
        st.info(
            "Gemma 연동에서 Timeout·연결 오류 같은 일시적 장애가 발생하면 Workflow 처음으로 돌아가지 않습니다. "
            "이미 만든 초안을 유지하고 실패한 Gemma 평가 호출만 최대 2회까지 다시 실행합니다. "
            "Trace의 status가 retrying이고 attempt가 1이면 실제 Provider Retry가 발생한 것입니다."
        )
        st.warning(
            "초안이 품질 기준을 통과하지 못한 경우는 Provider 오류와 다릅니다. "
            "Feedback을 반영해 OpenAI Reviser가 수정하고 다시 평가하며, 최대 평가 5회까지 통과하지 못하면 "
            "더 반복하지 않고 quality_failed 상태로 종료합니다."
        )
    st.write("실제 LLM 실행과 Redis Trace를 함께 확인합니다.")
    request_text = st.text_area(
        "여행 안내 요청",
        "부산 2박 3일 여행 안내문을 작성해 주세요. 예산은 예상 금액으로 안내하고, 외부 정보가 변동될 수 있으며 실제 결제는 사용자 승인 전에 실행하지 않는다고 명확히 적어 주세요.",
        height=140,
    )
    demonstrate_revision = st.checkbox("첫 초안에서 기준 하나를 의도적으로 누락해 Reviser 과정을 관찰합니다", value=True)
    if st.button("평가·Feedback Loop 실행", type="primary", width="stretch"):
        try:
            created = api_post("/api/runs", {"user_id": "user-101", "request": request_text, "demonstrate_revision": demonstrate_revision})
            st.caption(f"run_id: {created['run_id']}")
            st.session_state["evaluation-result"] = poll_run(created["run_id"])
        except (requests.RequestException, TimeoutError) as error:
            st.error(f"실행 오류: {error}")
    if "evaluation-result" in st.session_state:
        result = st.session_state["evaluation-result"]
        if result["status"] == "completed":
            st.success("품질 기준을 통과했습니다.")
        elif result["status"] == "quality_failed":
            st.warning("최대 5회 안에 품질 기준을 통과하지 못했습니다.")
        else:
            st.error("Provider 또는 실행 오류가 발생했습니다.")
        st.json(result.get("result"))
elif menu == "09 · 통합 여행 예약":
    render_travel_booking(labs)
elif menu == "10 · 예약 조회와 Trace":
    render_booking_history(labs)
elif menu == "11 · 예약 실패와 부분 복구":
    render_booking_recovery(labs)
else:
    show_lab_header("08", labs)
    st.subheader("전체 실행 흐름")
    st.graphviz_chart(
        r'''
        digraph SupportEvaluation {
            rankdir=LR;
            node [shape=box, style=rounded];
            request [label="고객지원 요청"];
            writer [label="OpenAI Writer\n답변 초안 작성"];
            evaluator [label="OpenAI Evaluator\nFeedback 생성"];
            gate [label="Python Quality Gate\n필수 문구 검사", shape=diamond];
            reviser [label="OpenAI Reviser\n실패 기준 수정"];
            completed [label="completed\n최종 답변"];
            failed [label="quality_failed\n4회 평가 후 종료"];
            request -> writer -> evaluator -> gate;
            gate -> completed [label="통과"];
            gate -> reviser [label="미통과"];
            reviser -> evaluator [label="재평가"];
            gate -> failed [label="4회까지 미통과"];
        }
        ''',
        width="stretch",
    )
    st.caption("품질 기준을 통과하면 즉시 종료하고, 미통과하면 Feedback을 반영해 최대 4회까지 평가합니다.")
    render_support_quality_criteria()
    st.subheader("LLM 최대 호출 구성")
    st.code(
        """Writer: 1회
Evaluator: 최대 4회
Reviser: 최대 3회
합계: 최대 8회""",
        language="yaml",
    )
    st.caption("품질 기준을 일찍 통과하면 남은 호출은 실행하지 않고 즉시 종료합니다.")
    request_text = st.text_area("고객지원 답변 요청", "로그인 오류 고객에게 확인 절차를 안내하고, 실제 계정 변경을 완료한 것은 아니라는 점을 알려 주세요.", height=120)
    demonstrate_revision = st.checkbox("첫 초안에서 기준 하나를 누락해 수정 과정을 봅니다", value=True, key="support-revision")
    if st.button("고객지원 평가·Feedback 실행", type="primary", width="stretch"):
        try:
            with st.spinner("OpenAI 작성 → OpenAI 평가 → 필요 시 OpenAI 수정 작업을 실행하고 있습니다..."):
                st.session_state["support-evaluation-result"] = api_post(
                    "/api/runs/support-evaluation",
                    {"request": request_text, "demonstrate_revision": demonstrate_revision},
                    timeout=180,
                )
        except requests.RequestException as error:
            st.error(f"실행 오류: {error}")
    if "support-evaluation-result" in st.session_state:
        result = st.session_state["support-evaluation-result"]
        if result["status"] == "completed":
            st.success(f"{result['rounds']}회 평가에서 {result['score']}점으로 통과했습니다.")
        else:
            st.warning("최대 4회 평가 안에 기준을 통과하지 못해 종료했습니다.")
        st.subheader("평가 기준")
        st.dataframe(result["criteria"], width="stretch")
        st.subheader("실행 순서")
        st.dataframe(result["trace"], width="stretch")
        with st.expander("전체 결과 보기"):
            st.json(result)
