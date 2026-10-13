# 프로젝트 계획서 · 공정 N빵 멀티 에이전트

> 멀티 에이전트 오케스트레이션 과정 미니 프로젝트 04
> 기준 문서: `MULTI_AGENT_PROJECT_PROPOSALS.md` (6장 진행 단계, 7장 완료 기준)

---

## 1. 기획

### 한 줄 소개

영수증 사진과 "누가 술을 안 마셨고, 누가 일찍 갔는지"를 말로 입력하면, 여러 Agent가 나눠서 정보를 정리하고 코드가 공정하게 계산해서 송금 목록과 단톡방 문구를 만들어 주는 서비스입니다.

### 해결하려는 문제

- 모임 비용을 똑같이 N빵하면 술을 안 마신 사람, 조금 먹은 사람, 1차만 있다 간 사람이 손해를 봅니다.
- 공정하게 나누려면 영수증을 보고 메뉴를 분류하고, 차수마다 참석자를 따지고, 결제자가 여러 명이면 송금을 상계해야 해서 계산이 번거롭습니다.
- 계산 결과가 왜 그렇게 나왔는지 설명하기 어려워서 단톡방에서 다시 물어보게 됩니다.

### 대상 사용자

회식, 동아리, 친구 모임에서 총무를 맡은 사람.

### 핵심 기능

1. 영수증 사진에서 메뉴와 금액 추출
2. 자연어 문장에서 참석·음주·먹은 양 추출
3. 메뉴를 "먹은 양 / 술 / 다같이 / 한 사람"으로 분류
4. 차수별 공정 계산과 송금 상계
5. 사람별 "왜 이 금액" 설명과 단톡방 문구

### 하지 않는 것

- 실제 송금, 결제, 메시지 발송 (문구 복사까지만)
- 계좌번호 등 금융 정보 저장
- LLM의 금액 계산 (계산은 항상 `computeSplit()`이 담당)

---

## 2. 요구사항

| ID | 기능 | 입력 | 출력 | 우선순위 |
| --- | --- | --- | --- | --- |
| F-01 | 수동 입력 계산 | 사람, 차수, 메뉴, 참석 정보 | 사람별 금액, 송금 목록 | **완료** |
| F-02 | 영수증 추출 | 영수증 이미지 | 메뉴·금액 목록, 총액 | MVP |
| F-03 | 상황 추출 | 자연어 문장 | 사람별 참석·음주·먹은 양 | MVP |
| F-04 | 메뉴 분류 | 메뉴 목록 | 메뉴별 나누는 방식 | MVP |
| F-05 | 분류 확인·수정 | 분류 결과 | 승인 또는 수정된 분류 | MVP |
| F-06 | 정보 부족 질문 | 빠진 결제자, 모르는 이름 | 사용자 질문 | MVP |
| F-07 | 금액 설명 | 계산 결과 | 사람별 설명 문장 | 확장 |
| F-08 | 실행 Trace 화면 | run_id | Agent별 실행 기록 | MVP |
| F-09 | 영수증 여러 장 병렬 처리 | 이미지 N장 | 차수별 메뉴 목록 | 확장 |
| F-10 | 중복 영수증 차단 | 같은 이미지 | "이미 등록됨" 안내 | 확장 |

---

## 3. Agent 설계

LLM Agent는 4개입니다. 계산은 Agent가 아니라 코드입니다.

### Receipt Agent (필수)

| 항목 | 내용 |
| --- | --- |
| Goal | 영수증 이미지에서 메뉴, 수량, 금액, 총액을 추출 |
| 책임 | 읽을 수 없는 줄은 `unreadable`로 표시 |
| Non-goals | 메뉴 분류, 금액 추측·보정 |
| 입력 계약 | `ReceiptInput(image_id, round_name)` |
| 출력 계약 | `ReceiptResult(items: list[ReceiptLine], printed_total: int, unreadable_lines: list[str])` |
| Tool | 없음 (이미지 입력 모델 사용) |
| Provider | OpenAI 기본, Gemini 대체 |
| 완료 조건 | `sum(items.amount) == printed_total` (Python 검사) |

### Situation Agent (필수)

| 항목 | 내용 |
| --- | --- |
| Goal | 문장에서 사람별 참석 차수, 음주 여부, 먹은 양, 결제자 추출 |
| 책임 | 문장에 없는 값은 비워 두고 `missing_information`에 기록 |
| Non-goals | 없는 사람 추가, 기본값 추측 |
| 입력 계약 | `SituationInput(message, known_people, round_names)` |
| 출력 계약 | `SituationResult(people: list[PersonState], payers: dict[round, name], missing_information: list[str])` |
| Tool | 없음 |
| Provider | OpenAI 기본, Gemini 대체 |
| 완료 조건 | 모든 차수에 결제자가 있고, 먹은 양 값이 0.5·1·1.5 중 하나 |

### Classifier Agent (필수)

| 항목 | 내용 |
| --- | --- |
| Goal | 메뉴마다 나누는 방식을 결정 |
| 책임 | "한 사람"이면 누구인지 함께 반환, 모르면 `unknown_owner` |
| Non-goals | 금액 변경, 메뉴 추가·삭제 |
| 입력 계약 | 메뉴 이름 목록 + Situation의 개인 메뉴 언급만 (최소 Context) |
| 출력 계약 | `ClassifiedItem(label, kind: Literal["food","alcohol","equal","personal"], owner: str \| None)` |
| Tool | `get_menu_category` (자주 나오는 메뉴 사전, PostgreSQL) |
| Provider | Ollama llama3.2 기본, OpenAI 대체 |
| 완료 조건 | 모든 메뉴가 4가지 값 중 하나로 분류됨 |

### Explainer Agent (선택)

| 항목 | 내용 |
| --- | --- |
| Goal | 사람별 부담액을 한두 문장으로 설명 |
| Non-goals | 금액 계산·변경 |
| 입력 계약 | 한 사람의 `detail` 목록과 최종 금액만 |
| 출력 계약 | `Explanation(name, text, amounts_mentioned: list[int])` |
| Provider | Gemma 3 1B |
| 완료 조건 | `amounts_mentioned`가 모두 계산 결과에 있는 값 (Python 검사) |

### 결정적 계산 (코드)

| 항목 | 내용 |
| --- | --- |
| 함수 | `computeSplit(state)` (`core/calc.js`, 백엔드에서는 Python으로 옮겨 사용) |
| 역할 | 차수별 분배, 반올림, 송금 상계 |
| 검증 | `tests/test_calc.js`, `tests/test_scenarios.js` 15개 |

---

## 4. 오케스트레이션 설계

### 전체 흐름

```text
사용자 입력 (영수증 이미지 N장 + 상황 문장)
        │
① 입력 계약 검사 ── 이미지 형식, 크기, 문장 길이 (LLM 0회)
        │
② Parallel
   ├─ Receipt Agent × 영수증 수 (차수마다 1개)
   └─ Situation Agent
        │  Join
③ Join Guard (Python)
   ├─ 영수증 합계 ≠ 총액 → 사용자에게 수정 요청 (중단)
   ├─ 결제자·이름 누락 → 사용자 질문 (중단)
   └─ 통과
        │
④ Classifier Agent ── 메뉴 이름만 전달
        │
⑤ 사용자 확인 (Human-in-the-loop)
   ├─ 승인 → ⑥
   └─ 수정 → 수정된 항목만 반영 (재분류 없이 사용자 값 우선)
        │
⑥ computeSplit() ── 결정적 계산
        │
⑦ Explainer Agent (선택) ── 실패해도 결과는 표시
        │
⑧ 결과 + 단톡방 문구 (발송은 사용자가 직접)
```

### 패턴별 위치

| 패턴 | 위치 | 이유 |
| --- | --- | --- |
| Parallel + Join | ② | 영수증 추출과 상황 추출은 서로 독립 |
| Sequential | ③ → ④ → ⑤ → ⑥ | 분류는 추출이 끝나야, 계산은 승인이 끝나야 가능 |
| Contract Guard | ①③⑥⑦ | 금액 합계, 분류값, 설명 속 숫자 검사 |
| Human-in-the-loop | ⑤ | 분류는 모임마다 다름 ("냉면은 다같이") |
| 필수·선택 구분 | ⑦ | 설명은 없어도 정산은 완료 |

Router와 Supervisor는 쓰지 않습니다. 순서가 항상 같아서 LLM이 다음 단계를 고를 필요가 없고, 순서를 코드로 고정하는 편이 비용과 안정성 면에서 낫습니다.

### State

```python
class SplitRunState(BaseModel):
    run_id: str
    receipts: dict[str, ReceiptResult]      # round_id → 추출 결과
    situation: SituationResult | None
    classified: list[ClassifiedItem]
    approved: bool = False
    split_result: dict | None                # computeSplit 결과
    explanations: dict[str, Explanation]
    status: Literal["running", "needs_information", "awaiting_approval",
                    "completed", "partial", "failed"]
```

### 최소 Context

| Agent | 받는 것 | 받지 않는 것 |
| --- | --- | --- |
| Receipt | 이미지 1장, 차수 이름 | 사람 이름, 다른 영수증 |
| Situation | 문장, 사람 목록, 차수 이름 | 영수증 금액 |
| Classifier | 메뉴 이름, 개인 메뉴 언급 | 금액, 결제자 |
| Explainer | 한 사람의 내역과 금액 | 다른 사람 금액 |

---

## 5. 아키텍처와 데이터

01~03 프로젝트와 같은 구조를 유지합니다.

```text
Streamlit :8501
  → FastAPI :8000
     ├─ SplitOrchestrator (Python 흐름 고정)
     ├─ computeSplit (Python)
     └─ Redis: 진행 상태 · Trace
  → FastMCP :8010
     └─ PostgreSQL: 메뉴 사전, 실행 기록
```

### API

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/api/split-runs` | 영수증·문장으로 실행 시작, `run_id` 반환 |
| GET | `/api/split-runs/{run_id}/snapshot` | 진행 상태와 Trace |
| POST | `/api/split-runs/{run_id}/answer` | 정보 부족 질문에 답변 |
| POST | `/api/split-runs/{run_id}/approve` | 분류 승인 또는 수정 |
| POST | `/api/split/calculate` | 수동 입력 계산 (LLM 없음) |

### 테이블

| 테이블 | 용도 |
| --- | --- |
| `menu_categories` | 메뉴 이름 → 기본 분류 (소주 → alcohol, 공기밥 → food) |
| `split_runs` | run_id, 상태, 생성 시각, 입력 해시(중복 방지) |
| `split_run_events` | Agent 시작·완료·실패, Provider, 재시도, 지연 시간 |

---

## 6. 안전 경계

| 규칙 | 적용 방법 |
| --- | --- |
| LLM은 금액을 계산하지 않음 | 계산은 `computeSplit()`만, Explainer 숫자는 결과와 대조 |
| Tool Allowlist | Classifier만 `get_menu_category` 사용 가능, 코드에서 검사 |
| 외부 전송 없음 | 단톡방 문구는 복사만 제공 |
| 개인정보 최소화 | 영수증 이미지는 추출 후 저장하지 않음, 카드번호 줄은 마스킹 |
| 추측 금지 | 빠진 값은 비워 두고 사용자에게 질문 |

---

## 7. 오류 대응 정책

계획서 4장의 `ExecutionPolicy`를 그대로 따릅니다.

| 상황 | 처리 |
| --- | --- |
| Timeout, 503 | 같은 Provider 1회 재시도 |
| 429 | 대기 시간 확인 후 1회 재시도 |
| Provider 반복 실패 | 대체 Provider로 전환, 같은 출력 계약으로 재검증 |
| 출력 계약 위반 | 1회 재생성, 또 실패하면 사용자 입력으로 전환 |
| 영수증 합계 불일치 | 재시도하지 않고 사용자에게 수정 요청 |
| 인증 오류 (401·403) | 즉시 중단, 다른 Provider로 숨기지 않음 |
| Explainer 실패 (선택) | 설명 없이 결과 표시, `partial` 상태 |
| 필수 Agent 최종 실패 | 수동 입력 화면으로 전환 |

```python
ExecutionPolicy(
    timeout_seconds=30,
    max_attempts=2,
    allow_provider_failover=True,
    required_agents={"receipt_agent", "situation_agent", "classifier_agent"},
    optional_agents={"explainer_agent"},
)
```

---

## 8. 관측과 Trace

- 모든 실행에 `run_id`를 붙입니다.
- 기록할 이벤트: `agent_start`, `agent_done`, `agent_error`, `retry`, `provider_failover`, `ask_user`, `approval`, `contract_failed`.
- 이벤트마다 Provider, 모델, 지연 시간, 토큰 수, 예상 비용을 남깁니다.
- Streamlit에서 Trace를 시간순으로 보여주고, 실행 1건당 LLM 비용 합계를 표시합니다.

---

## 9. 테스트 계획

시나리오 상세는 `docs/SCENARIOS.md`에 있습니다.

| 묶음 | 개수 | 방법 | 상태 |
| --- | --- | --- | --- |
| A. 계산 규칙 (S1~S8) | 8 | `node tests/test_scenarios.js` | **통과** |
| 계산 단위 테스트 | 7 | `node tests/test_calc.js` | **통과** |
| B-1 정상 | 3 | Agent를 가짜 응답으로 바꾼 unittest | 예정 |
| B-2 정보 부족 | 3 | 〃 | 예정 |
| B-3 부분 실패 | 4 | 장애 주입 unittest | 예정 |
| B-4 전체 실패 | 4 | 〃 | 예정 |
| B-5 승인·거부 | 4 | API 테스트 | 예정 |

---

## 10. 완료 기준 점검표

계획서 7장 기준입니다.

| 완료 기준 | 이 프로젝트에서 | 상태 |
| --- | --- | --- |
| Agent별 역할과 책임 분리 | 3장 Agent 설계 | 설계 완료 |
| 출력이 구조화 계약으로 검증 | 3장 출력 계약 + 합계 검사 | 설계 완료 |
| Routing·Parallel·Join·Handoff 중 2개 이상 | Parallel + Join, Sequential | 설계 완료 |
| Tool 권한을 코드에서 강제 | Classifier만 `get_menu_category` | 예정 |
| 최소 Context만 전달 | 4장 최소 Context 표 | 설계 완료 |
| 변경·외부 작업 전 승인 | 분류 승인, 발송은 사용자가 직접 | 설계 완료 |
| Timeout과 최대 재시도 | 7장 정책 | 예정 |
| 대체 경로와 중단 조건 | Provider 전환, 수동 입력 전환 | 예정 |
| 사용한 Provider·Tool이 Trace에 남음 | 8장 | 예정 |
| 필수·선택 실패 정책 구분 | Explainer만 선택 | 설계 완료 |
| 정상·부분 실패·전체 실패·승인 거부 테스트 | `docs/SCENARIOS.md` B 묶음 | 시나리오 완료, 코드 예정 |

---

## 11. 일정

| 주차 | 목표 | 결과물 |
| --- | --- | --- |
| 0주차 | 계산 규칙 확정 | `core/calc.js`, 화면, 테스트 15개 (**완료**) |
| 1주차 | 백엔드 뼈대 | FastAPI, `computeSplit` Python 이식, 수동 계산 API, 테스트 이식 |
| 2주차 | 추출 Agent | Situation Agent, Receipt Agent, 병렬 실행과 Join Guard |
| 3주차 | 분류와 승인 | Classifier Agent, MCP 메뉴 사전, 승인 API, Streamlit 확인 화면 |
| 4주차 | 안정성과 발표 | 재시도·Failover·Trace·비용 표시, B 묶음 테스트, 발표 데모 |
