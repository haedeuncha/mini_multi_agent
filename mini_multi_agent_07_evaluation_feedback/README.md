# Mini Multi-Agent 07 · Evaluation, Feedback, Retry and Tracing

01~06에서 만든 Agent 역할·계약·Orchestration·Handoff·Guardrail 구조 위에 결과 품질 개선과 실패 복구, 실행 추적을 추가합니다.

```text
PostgreSQL 평가 기준
        ↓
OpenAI Writer Agent
        ↓
Gemma Evaluator Agent
        ↓
Python Quality Gate
   ├─ 통과 → PostgreSQL 최종 이력 저장
   └─ 실패 → Feedback
                ↓
         OpenAI Reviser Agent
                ↓
         재평가 · 최대 5회

Redis Snapshot·Trace → Streamlit 1초 폴링
```

## 실제 구성

| 구성 요소 | 역할 |
| --- | --- |
| OpenAI `gpt-4.1-mini` | Writer와 Reviser |
| Ollama `gemma3:1b` | 로컬 독립 Evaluator |
| PostgreSQL | 평가 기준, 회차별 점수·Feedback, 최종 실행 이력 |
| Redis | 실행 중 Snapshot과 실시간 Trace |
| FastAPI | 실행 생성, 상태 조회, 이력 API |
| Streamlit | 왼쪽 학습 메뉴, Progress Bar, 평가 Trace |

Mock 성공 데이터로 실제 LLM이나 저장소 오류를 숨기지 않습니다. OpenAI·Gemma·Redis·PostgreSQL 중 하나가 실패하면 실패 종류와 복구 정책을 Trace에 남깁니다.

03·07의 로컬 Gemma 호출에서 일시적인 연결 오류가 발생하면 제한된 재시도를 수행합니다. Lab 08 고객지원 예제는 OpenAI 호출이 일시적으로 실패하면 한 번 더 시도하며, 계속 실패하면 API가 503과 오류 종류를 반환합니다. 실제 Provider 상태에 따라 수업 중 호출이 실패할 수 있습니다.

## 학습 메뉴

| 메뉴 | 학습 내용 |
| --- | --- |
| 01 Evaluation Criteria | PostgreSQL 평가 기준과 가중치 |
| 02 Evaluator Agent | LLM 평가와 Python Quality Gate |
| 03 Feedback Loop | Writer → Evaluator → Reviser |
| 04 Bounded Retry | 일시적 Provider 오류 최대 2회 |
| 05 Failure Policy | Retry·Replan·Block·Human Escalation |
| 06 Partial Recovery | 성공 결과 보존과 실패 부분 복구 |
| 07 Quality Trace | 생성·평가·수정 회차 전체 추적 |
| 08 다른 업무에 평가 적용 | 고객지원 답변 작성·평가·수정 |
| 09 통합 여행 예약 | 실제 날씨 → 장소·숙소 선택 → 1차 계획 승인 → 예산·가이드 → 2차 예약 승인 |
| 10 예약 조회와 Trace | 예약 이력 조회와 run_id 기반 전체 과정 확인 |
| 11 예약 실패와 부분 복구 | Booking MCP Retry, 성공 결과 보존, 멱등성 예약 복구 |
| Agent Registry·YAML | Agent 정의와 실행 정책 비교 |
| PostgreSQL 실행 이력 | 종료 후에도 남는 평가 회차 조회 |

각 Lab 화면에는 생각할 질문의 핵심 답변과 상세 설명, 예상 LLM 호출 수,
`실행 후 먼저 읽을 코드`와 `실행 결과 분석 질문`이 함께 표시됩니다.

01~06은 이전 과정처럼 `실습 흐름도 → 값 선택 또는 실행 버튼 → 실행 결과` 순서로 진행합니다.
01·05·06은 Backend API에서 실제 기준과 사례를 가져오고, 02·04는 외부 LLM을 호출하지 않는
결정적인 수업용 비교를 실행합니다. 03은 실제 Writer → Evaluator → Reviser 흐름을 실행하고
화면에서 Progress와 Trace를 확인합니다.

## 디렉터리 구조

```text
backend/app/
├─ agents/
│  ├─ definitions/evaluation_policies.yaml
│  ├─ writer_agent.py
│  ├─ evaluator_agent.py
│  ├─ reviser_agent.py
│  └─ registry.py
├─ database/
│  ├─ repository.py
│  └─ init_db.py
├─ orchestration/
│  ├─ engine.py
│  ├─ support_flow.py         # 고객지원 평가 적용 예제
│  └─ failure_policy.py
├─ observability/tracker.py
├─ providers/registry.py
├─ schemas/contracts.py
├─ storage/redis_store.py
└─ routers/evaluation.py
frontend/app.py
sql/001_evaluation_schema.sql
```

## Python·YAML·PostgreSQL의 책임

| 위치 | 관리하는 내용 |
| --- | --- |
| Python AgentProfile | Agent 이름·목표·설명·명확한 지시문 |
| YAML | Provider 배정, 최대 5회 평가, 최대 2회 Retry, 최소 점수 |
| PostgreSQL | 실제 평가 기준과 가중치, 실행 및 평가 회차 이력 |
| Python Orchestrator | 조기 종료, 최대 반복, 실패 분류, Quality Gate 강제 |
| Redis | 화면이 빠르게 조회할 현재 상태와 Trace |

평가 기준을 PostgreSQL에 둔 이유는 운영 중 기준을 조회·변경·버전 관리하고 실행 이력과 연결하기 위해서입니다. 반복 횟수와 Provider 같은 실행 설정은 YAML로 읽기 쉽게 관리하지만 최종 종료는 Python이 강제합니다.


## Trace에 남기면 안 되는 정보

Trace는 Agent 실행 흐름을 이해하기 위한 기록입니다. 하지만 모든 입력과 출력을 그대로 저장하면 보안 문제가 생길 수 있습니다.

다음 정보는 Trace, Redis Snapshot, PostgreSQL 이력에 남기지 않습니다.

- API Key
- 비밀번호
- 인증 Token
- 결제 정보
- 주민등록번호, 전화번호, 주소 같은 불필요한 개인정보
- 전체 Prompt 원문
- 외부 Provider 응답 원문 중 민감정보가 포함될 수 있는 내용

07 과정에서는 Redis에 진행 중인 Snapshot과 화면용 Trace를 저장합니다. PostgreSQL에는 평가 기준, 평가 회차, 예약 이력처럼 수업에 필요한 구조화된 정보만 저장합니다.

운영 환경에서 시간순 감사 로그, 장기 보관 정책, 마스킹, 접근 권한 관리까지 연결하는 구현은 08 과정에서 다룹니다.

## 데이터베이스 테이블

```text
mini_multi_agent_07.evaluation_criteria
  평가 항목 · 필수 문구 · 가중치 · 필수 여부

mini_multi_agent_07.evaluation_runs
  요청 · 상태 · 최종 점수 · 최종 답변 · 오류

mini_multi_agent_07.evaluation_rounds
  회차 · 초안 · 점수 · Feedback · 실패 기준 · Provider · 지연 시간

mini_multi_agent_07.booking_records
  사용자 선택 후 Booking MCP 서버가 저장한 숙소 예약
```

Redis Key는 다음처럼 분리합니다.

```text
mini07:run:{run_id}         현재 Snapshot
mini07:run:{run_id}:events  화면용 구조화 Trace
```

## 환경 준비

별도 Docker Compose는 만들지 않고 이전 과정에서 실행한 PostgreSQL과 Redis 컨테이너를 사용합니다.

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

다른 PC에서 복사한 `.venv`는 원래 Python 경로를 기억하므로 실행되지 않을 수 있습니다.
이 경우 현재 PC에서 가상환경을 다시 만들고 `pip install -r requirements.txt`를 실행합니다.
09를 실행하려면 `mcp[cli]`도 설치되어 있어야 합니다.

OpenAI API Key와 로컬 Ollama 주소를 설정합니다. Gemma는 별도의 API Key가 필요하지 않습니다.

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OLLAMA_BASE_URL=http://127.0.0.1:11434
GEMMA_MODEL=gemma3:1b
REDIS_URL=redis://127.0.0.1:6379/0
DATABASE_URL=postgresql://agent_user:agent_pwd@127.0.0.1:5433/agent_db
WEATHER_MCP_URL=http://127.0.0.1:18012/mcp
WEATHER_MCP_PORT=18012
HOTEL_MCP_URL=http://127.0.0.1:18011/mcp
HOTEL_MCP_PORT=18011
BOOKING_MCP_URL=http://127.0.0.1:18010/mcp
BOOKING_MCP_PORT=18010
API_BASE_URL=http://127.0.0.1:18000
```

Backend를 실행하기 전에 Ollama에 수업용 Gemma 모델을 한 번 내려받고 실행 상태를 확인합니다.

```powershell
ollama pull gemma3:1b
ollama list
```

03 Feedback Loop의 역할은 다음처럼 나뉩니다.

```text
OpenAI Writer → Gemma Evaluator → Python Quality Gate
       ↑                              │
       └──── OpenAI Reviser ← Feedback┘
```

OpenAI가 결과 생성과 수정을 담당하고, 로컬 `gemma3:1b`는 보조 Evaluator로서 Feedback을 만듭니다. 최종 통과 여부는 Gemma의 판단만 사용하지 않고 Python Quality Gate가 다시 검사합니다.

## PostgreSQL 초기화

최초 한 번 실행합니다. 기존 테이블을 삭제하지 않으며 Seed는 같은 키를 기준으로 갱신됩니다.

```powershell
python .\sql\apply_schema.py
python .\check_environment.py
```

09 예약 필드가 추가된 이전 버전의 DB를 사용 중인 경우에도 `apply_schema.py`를 다시 실행합니다. 기존 예약은 삭제하지 않고 `total_budget`, `travel_guide`, 두 승인 시각 컬럼만 안전하게 추가합니다. 스키마 적용 후 실행 중인 Booking MCP 서버도 다시 시작해야 새 Tool 입력 형식이 반영됩니다.

## 다섯 Process 실행

09 통합 예제에서 실제 날씨, 주변 숙소, 예약을 차례로 처리하므로 Weather·Hotel·Booking MCP 서버가 모두 필요합니다.

터미널 1 · Backend:

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 18000 --app-dir backend
```

터미널 2 · Weather MCP 서버:

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
python .\mcp_weather_server\main.py
```

터미널 3 · Hotel MCP 서버:

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
python .\mcp_hotel_server\main.py
```

터미널 4 · Booking MCP 서버:

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
python .\mcp_booking_server\main.py
```

터미널 5 · Frontend:

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
streamlit run .\frontend\app.py --server.port 18570
```

- 화면: `http://127.0.0.1:18570`
- API 문서: `http://127.0.0.1:18000/docs`
- Weather MCP endpoint: `http://127.0.0.1:18012/mcp`
- Hotel MCP endpoint: `http://127.0.0.1:18011/mcp`
- Booking MCP endpoint: `http://127.0.0.1:18010/mcp`

## 주요 API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | `/api/labs` | 11개 학습 메뉴 |
| GET | `/api/registry` | Python Agent와 YAML 실행 정책 |
| GET | `/api/criteria` | PostgreSQL 평가 기준 |
| GET | `/api/failure-cases` | 오류별 복구 정책 |
| GET | `/api/partial-recovery` | 부분 복구 구조 |
| GET | `/api/providers` | 실제 LLM 상태 |
| POST | `/api/runs` | Feedback Loop 실행 생성 |
| GET | `/api/runs/{run_id}` | Redis Snapshot·Trace 폴링 |
| GET | `/api/history` | PostgreSQL 실행 이력 |
| GET | `/api/history/{run_id}/rounds` | 회차별 점수와 Feedback |
| POST | `/api/runs/support-evaluation` | 고객지원 평가·Feedback 실행 |
| POST | `/api/travel-booking/plan` | 실제 날씨에 맞는 장소 후보 생성과 평가 |
| POST | `/api/travel-booking/hotels` | 사용자가 선택한 장소 주변 숙소 검색과 평가 |
| POST | `/api/travel-booking/prepare` | 1차 승인 후 전체 예산과 여행 가이드 생성 |
| POST | `/api/travel-booking/book` | 2차 승인 후 Booking MCP 호출과 DB 저장 |
| POST | `/api/travel-booking/recovery-demo` | 11의 전체 흐름과 선택한 예약 장애·Retry를 한 번에 실행 |
| GET | `/api/travel-booking/{run_id}` | 여행 예약 흐름 Snapshot·Trace 조회 |
| GET | `/api/bookings` | PostgreSQL 예약 이력 조회 |

## Lab 08 · 다른 업무에 평가 적용

여행 안내문에서 배운 평가 구조를 고객지원 답변에 적용합니다. 새 데이터베이스를 만들지
않고 코드에 보이는 두 가지 기준만 사용해 작성→평가→수정 흐름에 집중합니다.

```text
고객지원 요청
→ OpenAI support_writer_agent가 초안 작성
→ OpenAI support_evaluator_agent가 Feedback 작성
→ Python이 필수 문구와 점수 확인
   ├─ 100점 → 완료
   └─ 실패 → OpenAI support_reviser_agent 수정 → 최대 4회까지 평가
```

평가 기준은 다음 두 가지이며 각각 50점, 모두 필수입니다.

- 답변에 `확인 절차`가 포함되어야 합니다.
- 답변에 `실제 변경을 완료하지 않았습니다`가 포함되어야 합니다.

첫 초안 누락 옵션을 켜면 두 번째 기준을 의도적으로 빠뜨려 Reviser 과정을 관찰합니다.
옵션을 끄고 첫 초안이 두 기준을 모두 충족하면 첫 평가에서 즉시 종료합니다.
08의 호출 수는 최소 2회이며, `Writer 1회 + Evaluator 최대 4회 + Reviser 최대 3회`로 최대 8회입니다.
08은 Writer·Evaluator·Reviser를 모두 OpenAI로 실행하므로 여러 요청을 순서대로 처리할 때 일반 API보다 오래 걸릴 수 있습니다.
화면은 최대 180초까지 기다리며, 실행 중에는 Spinner를 표시합니다.

학생은 다음 파일을 먼저 읽습니다.

- `backend/app/orchestration/support_flow.py`의 `run_support_evaluation()`
- 같은 파일의 `evaluate_support_text()`

기존 여행 예제는 PostgreSQL 기준과 실행 이력을 사용하는 운영형 흐름이고, 고객지원
예제는 동일한 원리를 짧게 확인하기 위한 학습용 흐름입니다.

## 반복과 호출 수

```text
최대 평가 회차: 5
최대 Reviser 실행: 4
Provider Retry: 호출별 최대 2회
품질 통과: 즉시 조기 종료
```

Provider 오류가 없으면 논리적인 LLM 호출은 최소 2회, 최대 10회입니다. 모든 호출이 일시적 오류 후 성공하는 극단적인 경우 실제 Provider 요청은 최대 20회가 될 수 있습니다. 수업에서는 비용과 시간을 고려해 한 팀씩 실행하는 것을 권장합니다.

07 Quality Trace 화면에서는 두 반복을 구분해서 읽습니다.

- Gemma의 일시적인 호출 오류: 기존 초안을 유지하고 실패한 Gemma 평가 호출만 최대 2회 실행합니다. 첫 실패는 Trace에 `status=retrying`, `attempt=1`로 표시됩니다.
- 초안의 품질 기준 미통과: Feedback을 OpenAI Reviser에게 전달하고 수정된 초안을 다음 회차에서 다시 평가합니다.
- 품질 평가가 최대 5회까지 통과하지 못하면 더 반복하지 않고 `quality_failed`로 종료합니다.
- Gemma 호출이 두 번 모두 실패하면 품질 평가를 계속할 수 없으므로 전체 실행은 `failed`로 종료합니다.

## 수업 실습 순서

1. PostgreSQL의 네 평가 기준과 필수 여부를 확인합니다.
2. Feedback Loop를 실행하고 Redis Progress Bar를 확인합니다.
3. `첫 초안에서 기준 하나를 의도적으로 누락`을 선택하고 Evaluator 점수와 실패 기준을 확인합니다.
4. Reviser가 받은 Feedback과 다음 초안의 차이를 비교합니다.
5. 기준 통과 시 5회 전에 종료되는지 확인합니다.
6. PostgreSQL 실행 이력에서 같은 `run_id`의 평가 회차를 다시 조회합니다.
7. API Key 하나를 잘못 설정해 실패 정책과 Trace가 남는지 확인합니다.

## 완료 기준

- Validation, Evaluation, Feedback, Retry의 차이를 설명할 수 있습니다.
- OpenAI Writer와 Gemma Evaluator의 책임을 구분할 수 있습니다.
- 최대 5회와 조기 종료가 Python에서 강제되는 위치를 찾을 수 있습니다.
- Redis 현재 상태와 PostgreSQL 영구 이력의 차이를 설명할 수 있습니다.
- 회차별 점수·Feedback·Provider·지연 시간을 화면에서 추적할 수 있습니다.
- 성공 결과를 보존하고 실패한 Agent만 복구해야 하는 이유를 설명할 수 있습니다.
- 고객지원 답변에서도 작성·평가·수정과 조기 종료를 설명할 수 있습니다.

## 검증

환경 진단은 실제 실행 Provider인 OpenAI·Gemma, Redis, PostgreSQL 평가 기준과 07 Backend를
검사하며 하나라도 실패하면 종료 코드 `1`을 반환합니다.

```powershell
python -m unittest discover -s tests -v
python .\check_environment.py
```

Python AgentProfile과 YAML Provider가 다르거나 반복·점수 범위가 잘못되면 애플리케이션
시작 단계에서 차단합니다. Provider 오류는 안전한 오류 코드로 정규화하고, 일시적 연결
오류 또는 재시도 시간이 제공된 429만 제한된 Retry 대상으로 처리합니다.


## Labs 09~11 · 통합 여행 예약, 조회와 부분 복구

09는 앞의 평가·Feedback·Retry·Trace 개념을 하나의 예약 실행으로 묶고, 10은 완료된 예약을 조회합니다. 11은 마지막 예약 단계의 오류를 재현하고 성공한 앞 단계는 보존한 채 Booking MCP만 복구합니다.

```text
사용자 여행 요청
  → Weather MCP 서버에서 실제 날씨 조회
  → 실제 날씨 기반 장소 후보 생성
  → 장소 추천 품질 평가
  → 사용자가 장소 하나 선택
  → Hotel MCP 서버에서 선택 장소 주변 숙소 후보 조회
  → 숙소 후보 품질 평가
  → 사용자가 숙소·날짜·인원 확인
  → 1차 승인
  → Python Budget Agent가 전체 예상 예산 계산
  → OpenAI Guide Writer가 여행 가이드 작성
  → Python Quality Gate가 필수 항목 검사
     └─ 실패하면 OpenAI Guide Reviser가 한 번 수정
  → 예산·가이드 확인
  → 2차 승인: 실제 예약 실행 허용
  → Booking MCP 서버 호출
  → Booking MCP 서버 콘솔 출력
  → PostgreSQL booking_records 저장
  → 예약 이력과 Trace 조회
```

이 예제의 핵심은 계획 생성과 실제 외부 변경을 두 번의 승인으로 분리하는 것입니다. 1차 승인은 Budget Agent 계산과 OpenAI 여행 가이드 생성을 허용하고, 2차 승인 전에는 Booking MCP나 PostgreSQL 저장이 실행되지 않습니다. 금액은 LLM이 아니라 Python이 계산하며, LLM은 문장과 일정을 만드는 데만 사용합니다.

같은 `run_id`의 상태는 다음 순서로 바뀝니다.

```text
waiting_for_place_selection
→ waiting_for_hotel_selection
→ waiting_for_booking_approval
→ booked
```

Hotel MCP 또는 Booking MCP 호출이 실패하면 `hotel_search_failed` 또는 `booking_failed`로 남아 원인을 Trace에서 확인할 수 있습니다.

### 시드 데이터와 실행 순서

09 화면에서 사용자는 사용자 ID와 지역만 먼저 확인합니다. `여행 시작`을 누르면 Backend가 Weather MCP를 자동 호출하고, 그 결과를 바로 장소 추천에 사용합니다. 장소와 숙소·일정·인원을 선택한 뒤 1차 승인하면 Python Budget Agent가 예산을 계산하고 OpenAI가 여행 가이드를 작성합니다. Python Quality Gate에서 누락을 발견하면 OpenAI가 한 번 수정하므로 LLM은 최소 1회, 최대 2회 호출됩니다. 이 내용을 확인하고 2차 승인해야 Booking MCP가 호출됩니다.

수업용 장소 시드는 부산 3곳이며, 각 장소마다 숙소 3곳씩 총 9개의 숙소 시드가 Hotel MCP에 들어 있습니다. 현재 화면에서는 부산만 선택할 수 있습니다. 실제 날씨 조회가 실패하면 화면의 `source`가 `fallback`으로 표시되며, 이 경우 실제 관측값이 아닙니다. 별도의 날씨 입력 단계는 두지 않습니다.
실행 명령은 위의 [다섯 Process 실행](#다섯-process-실행)을 따릅니다.

### 확인할 것

- 09 화면: 실제 날씨에 맞는 장소가 먼저 추천되고, 선택한 장소 주변 숙소만 표시되는가?
- 09 화면: 1차 승인 뒤 예산과 가이드는 생성되지만 예약과 DB 저장은 아직 실행되지 않는가?
- 09 화면: 전체 내용을 확인한 2차 승인 뒤에만 Booking MCP와 DB 저장이 실행되는가?
- Weather MCP 서버 콘솔: 실제 날씨 조회 요청과 결과가 출력되는가?
- Hotel MCP 서버 콘솔: 숙소 조회 요청과 반환 결과가 출력되는가?
- Booking MCP 서버 콘솔: 예약 요청과 저장 완료 로그가 출력되는가?
- 10 화면: PostgreSQL 예약 이력과 같은 run_id의 전체 Trace를 다시 조회할 수 있는가?

### Lab 11 · 예약 실패와 부분 복구

11은 시작 화면에서 예약 장애 시나리오를 선택하고 날씨 조회부터 예약 복구까지 한 번에 실행합니다. 장소와 숙소는 최고 점수 후보를 자동 선택하며, 사용자가 동의하면 수업용 1차·2차 승인 이벤트를 Trace에 남깁니다.

```text
장애 시나리오 선택
→ 날씨·장소·숙소·예산·OpenAI 가이드 자동 진행
→ 수업용 1차·2차 승인
→ Booking MCP 호출
   ├─ 성공 → booked
   └─ 일시적 오류 → 같은 예약 정보로 최대 2회 Retry
                         ├─ 성공 → booked
                         └─ 실패 → booking_failed
                                      → 사용자가 예약 단계만 다시 실행
```

화면에서 `정상 예약`, `첫 호출만 실패`, `두 번 모두 실패`를 선택할 수 있습니다. 두 번 실패한 뒤 수동 복구할 때는 날씨 조회, 장소·숙소 선택, Budget Agent, OpenAI 가이드와 승인을 다시 실행하지 않습니다. `run_id`는 멱등성 키로 사용되며 Booking MCP의 기존 예약 확인과 PostgreSQL UNIQUE 인덱스가 중복 저장을 막습니다.

### MCP 서버 실행 방식

날씨·숙소·예약 서버는 FastMCP의 `streamable-http` 방식으로 실행합니다.
위의 터미널 2~4 명령으로 각각 시작하며 `/mcp` 주소에서 Tool을 제공합니다.
Backend의 `mcp_client.py`가 MCP 세션을 열어 Tool을 호출합니다.
`/docs`는 FastAPI Backend에만 있습니다.
