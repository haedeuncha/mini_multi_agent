# 09-30 Workshop · Lab 10 공정 N빵 정산 Supervisor–Worker

04 프로젝트(`mini_multi_agent_04_fair_split`)에서 설계한 시나리오를 03 프로젝트의
Supervisor–Worker 구조로 구현했습니다. 코드에서 `[Workshop N]` 주석을 검색하면 단계별 변경 위치가 나옵니다.

```text
split_supervisor_agent (Python · OpenAI)   다음 Worker만 제안, 허용 전이는 Python이 검사
  → receipt_agent    (YAML · OpenAI · get_receipt)            영수증 원문 → 메뉴·금액·결제자
  → situation_agent  (YAML · OpenAI · get_gathering_members)  문장 → 참석 차수·술·먹은 양
  → classifier_agent (YAML · Llama  · get_menu_categories)    메뉴 이름 → food/alcohol/equal/personal
  → python_calculator (LLM 없음)                               compute_split() 금액·송금
  → explainer_agent  (YAML · Gemma · 선택 Worker)              사람별 설명, 실패해도 partial
  → finish
```

## 단계별 변경 파일

| 단계 | 작업 | 파일 | 새 파일 |
| --- | --- | --- | --- |
| 1 | Agent 선언 (YAML) | `backend/app/agents/definitions/workers.yaml` 끝에 Worker 4개 (`group: split`) | |
| 2 | Registry · Loader 등록 | `agents/split_supervisor_agent.py`, `agents/registry.py` (`SPLIT_SUPERVISOR_AGENT`, `agents_in_group()`), `agents/loader.py` (`group`, `validate_worker_agents()`), `agents/models.py` (`group` 필드) | `split_supervisor_agent.py` |
| 3 | Tool 추가 (Mock) | `mcp_server/tools/split_tools.py`, `mcp_server/mock_data/split_gatherings.json`, `mcp_server/main.py` (Tool 등록), `agents/runtime.py` (`tool_arguments()`에 GATHER-번호) | `split_tools.py`, `split_gatherings.json` |
| 4 | Orchestration (engine.py 88라인 `supervisor_loop()` 참고, 별도 파일) | `orchestration/split_flow.py`, `orchestration/split_calculator.py`, `schemas/split.py` | 세 파일 모두 새 파일 |
| 5 | Router 연결 | `routers/workflow.py` (3개 API + async `split-settlement`), `services/catalog.py` (`LABS["10"]`, `SPLIT_CASES`) | |
| 6 | 테스트 · 화면 | `tests/test_split_lab10.py`, `frontend/app.py` (메뉴 `10 · 공정 N빵 정산 Supervisor`, `show_split_settlement()`) | `test_split_lab10.py` |

## engine.py `supervisor_loop()`와 비교

| | engine.py (Lab 05·07) | split_flow.py (Lab 10) |
| --- | --- | --- |
| 다음 Worker 결정 | 고정 목록 `plan[len(completed)]` | `expected_next(state)`가 검증된 State로 계산 |
| Worker 입력 | 요청 + 이전 결과 전체 | `worker_prompt()`가 Worker별 최소 Context만 (분류 Agent에는 금액 없음) |
| 결과 검증 | 결과가 있는지 | 계약 + `verify_worker()` 업무 규칙 (영수증 합계, 원문에 없는 금액, 멤버, 메뉴 누락, 설명 속 금액) |
| 계산 | 없음 | `compute_split()` (Python, LLM 호출 수에 포함 안 함) |
| 실패 정책 | 모든 실패 중단 | 필수 Worker 실패 중단, 선택 Worker(explainer) 실패는 `partial` |
| 종료 상태 | completed / blocked / failed | + `needs_information`, `needs_attention`, `partial` |

## 실행 순서

MCP → Backend → Frontend 순서는 기존과 같습니다. **MCP Server를 재시작해야** 새 Tool 3개가 등록됩니다.

```powershell
python .\mcp_server\main.py
uvicorn app.main:app --reload --port 8000 --app-dir backend
streamlit run .\frontend\app.py --server.port 8501
```

## Swagger 테스트 (`http://127.0.0.1:8000/docs`)

아래 순서대로 누르면 LLM 호출이 적은 것부터 확인할 수 있습니다.

| 순서 | API | 입력 | 기대 결과 | LLM |
| --- | --- | --- | --- | --- |
| ① | `GET /api/mcp-status` | - | `tool_count: 6`, `get_receipt` 등 3개 추가 | 0 |
| ② | `GET /api/split/tools-preview/{gathering_id}` | `GATHER-0930` | 영수증 2장, 멤버 5명, 메뉴 사전 | 0 |
| ③ | `GET /api/split-cases` | - | 요청 예시 4개 | 0 |
| ④ | `POST /api/runs/split-settlement` | `{"message": "어제 회식비 공정하게 나눠 줘."}` | `needs_information` · `gathering_id_missing` | 0 |
| ⑤ | 〃 | `{"message": "GATHER-1001 정산해 줘. 다들 술 마셨어."}` | `needs_attention` · "차이 3,000원" | 2 |
| ⑥ | 〃 | `{"message": "GATHER-0930 정산해 줘. 은비도 2차에 잠깐 왔어."}` | `needs_information` | 4 |
| ⑦ | 〃 | 정상 예시 (아래) | `completed` 또는 `partial` | 최대 9 |

정상 예시:

```json
{"message": "GATHER-0930 정산해 줘. 서준이랑 하은이는 술 안 마셨고 1차만 있다 갔어. 도윤이는 많이 먹었고 지영이는 조금 먹었어. 사이다는 하은이 거야."}
```

⑦의 기대 송금 (먹은 양은 사람 단위로 모든 차수에 적용):

| 보내는 사람 | 받는 사람 | 금액 |
| --- | --- | --- |
| 지영 | 민수 | 5,500원 |
| 서준 | 민수 | 16,400원 |
| 하은 | 민수 | 18,400원 |
| 도윤 | 민수 | 36,300원 |
| 도윤 | 지영 | 18,000원 |

LLM이 상황을 다르게 해석하면 금액이 달라질 수 있습니다. 그때는 Trace의 `situation_agent` 결과(`people`)를 먼저 확인하세요.

## 화면 연결

Streamlit 왼쪽 메뉴 **10 · 공정 N빵 정산 Supervisor**

1. "Mock Tool 데이터 미리 보기"에서 MCP Tool 3개 호출 (LLM 0회)
2. 요청 예시 선택 → "정산 Supervisor 실행" (비동기 실행 + Redis Polling)
3. 정산 결과(송금표, 사람별 차수 금액, 설명) → 실행 Trace → 최종 State 순서로 확인

## 테스트

```powershell
python -m unittest tests.test_split_lab10
```

16개 테스트 (시나리오 상세는 `SCENARIOS_LAB10.md`): Registry 등록, Mock Tool, Python 계산, 정상 완료(9회 호출·최소 Context), 모임 번호 없음(LLM 0회),
영수증 합계 불일치, 원문에 없는 금액 차단, 멤버가 아닌 이름, Supervisor 순서 위반 차단, 설명 금액 오류 → partial,
N3 스터디 뒤풀이, I3 결제자 비멤버, F3 메뉴 누락, F4 개인 메뉴 주인 불참, F5 Provider 장애, F6 없는 모임.

## 생각해 볼 질문

- Trace의 `python_calculator` 단계는 왜 LLM 호출 수(최대 9회)에 들어가지 않나요?
- 분류 Agent Prompt에서 금액을 뺀 이유는 무엇인가요?
- GATHER-1001은 왜 계산하지 않고 사람에게 넘기나요? 합계를 맞추도록 LLM에게 다시 시키면 어떤 위험이 있나요?
- 이 업무는 순서가 늘 같습니다. Supervisor 없이 Python 순차 실행으로 바꾸면 무엇이 달라질까요?
