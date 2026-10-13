# Lab 10 시나리오 · 공정 N빵 정산 Supervisor–Worker

Mock 데이터: `mcp_server/mock_data/split_gatherings.json`
자동 테스트: `python -m unittest tests.test_split_lab10` (LLM 응답을 가짜로 바꿔 흐름과 Guard를 검사)
화면 예시: Streamlit **10 · 공정 N빵 정산 Supervisor** 의 요청 예시 (`services/catalog.py · SPLIT_CASES`)

## Mock 모임

| 모임 | 내용 | 쓰는 시나리오 |
| --- | --- | --- |
| GATHER-0930 | 금요일 팀 회식 · 5명 · 1차 삼겹살(민수 결제 119,000) · 2차 호프(지영 결제 43,000) | N1, N2, N4, N5, I2, I4 |
| GATHER-1001 | 동아리 뒤풀이 · 3명 · 영수증 한 줄 판독 불가 (메뉴 합계 57,000 ≠ 인쇄 합계 60,000) | A1 |
| GATHER-1002 | 동아리 MT 장보기 · 3명 · **동아리회비카드**로 결제 (결제자가 멤버가 아님) | I3 |
| GATHER-1003 | 주말 스터디 뒤풀이 · 4명 · 1차 파스타(수아 결제 93,000) · 2차 카페(준호 결제 21,000) | N3 |
| GATHER-1004 | 제품 릴리스 축하 · 4명 · 1차 저녁(유나 100,000) · 2차 카페(민재 24,000) · 3차 택시(현우 32,000) | N6 |
| GATHER-1005 | 프로젝트 종료 회식 · 5명 · 1차 식사 · 2차 펍 · 3차 노래방 · 4차 택시 | N7 |

## 한눈에 보기

| ID | 구분 | 요청 (message) | 멈추는 곳 | 상태 | LLM 호출 | 자동 테스트 | 화면 예시 |
| --- | --- | --- | --- | --- | ---: | :---: | :---: |
| N1 | 정상 | GATHER-0930 · 술 안 마심·1차만·많이/조금·사이다 주인 | finish | completed | 9 | ✅ | ✅ |
| N2 | 정상 | GATHER-0930 · 모두 끝까지, 다 마심 | finish | completed | 9 | | ✅ |
| N3 | 정상 | GATHER-1003 · 운전자 술 안 마심·카페 불참·콜라 주인 | finish | completed | 9 | ✅ | ✅ |
| N4 | 정상 | GATHER-0930 · 1차 전원 음주, 2차는 민수·지영·도윤 | finish | completed | 9 | | ✅ |
| N5 | 정상 | GATHER-0930 · 1차 전원 음주, 서준·하은은 2차 전 귀가 | finish | completed | 9 | | ✅ |
| N6 | 정상 | GATHER-1004 · 3차까지 전원 참석, 저녁·카페·택시 | finish | completed | 9 | ✅ | ✅ |
| N7 | 정상 | GATHER-1005 · 4차까지 전원 참석, 식사·펍·노래방·택시 | finish | completed | 9 | ✅ | |
| I1 | 정보 부족 | 모임 번호 없음 | Python (LLM 전) | needs_information | **0** | ✅ | ✅ |
| I2 | 정보 부족 | GATHER-0930 · 멤버가 아닌 "은비" | situation_agent | needs_information | 4 | ✅ | ✅ |
| I3 | 정보 부족 | GATHER-1002 · 회비 카드 결제 | situation Guard (결제자) | needs_information | 4 | ✅ | ✅ |
| I4 | 정보 부족 | GATHER-0930 · 2차 참석자가 불명확 | situation_agent | needs_information | 4 | | ✅ |
| A1 | 사람 확인 | GATHER-1001 · 판독 불가 줄 | receipt Guard (합계) | needs_attention | 2 | ✅ | ✅ |
| F1 | 차단 | Supervisor가 순서를 건너뜀 | Python 전이 검사 | blocked | 1 | ✅ | |
| F2 | 실패 | receipt_agent가 원문에 없는 금액 작성 | receipt Guard (원문 대조) | failed | 2 | ✅ | |
| F3 | 실패 | classifier_agent가 메뉴 하나 누락 | classifier Guard | failed | 6 | ✅ | |
| F4 | 실패 | 2차에 없던 사람을 개인 메뉴 주인으로 지정 | classifier Guard | failed | 6 | ✅ | |
| F5 | 실패 | OpenAI 연결 실패 | Supervisor 결과 없음 | failed | 1 | ✅ | |
| F6 | 실패 | GATHER-9999 (없는 모임) | receipt Guard (Tool 실패) | failed | 2 | ✅ | ✅ |
| P1 | 부분 실패 | 설명에 계산 결과에 없는 금액 | explainer Guard | partial | 9 | ✅ | |
| P2 | 부분 실패 | 설명 Agent(Gemma) 시간 초과 | explainer 결과 없음 | partial | 9 | ✅ | |

LLM 호출 수는 Supervisor와 Worker를 합친 수입니다. `python_calculator` 단계는 들어가지 않습니다.

---

## 정상

### N1 · 금요일 팀 회식

```text
GATHER-0930 정산해 줘. 서준이랑 하은이는 술 안 마셨고 1차만 있다 갔어.
도윤이는 많이 먹었고 지영이는 조금 먹었어. 사이다는 하은이 거야.
```

Worker가 만들어야 할 결과

| Worker | 기대 결과 |
| --- | --- |
| receipt_agent | R1 7줄 (합계 119,000, 결제 민수), R2 2줄 (합계 43,000, 결제 지영) |
| situation_agent | 서준·하은: R1만, 술 X / 도윤: 많이 / 지영: 적게 / 민수: 보통 |
| classifier_agent | 참이슬·카스·생맥주 → alcohol, 칠성사이다 → personal(하은), 나머지 → food |

기대 결과 (Python 계산)

| 이름 | 1차 | 2차 | 합계 |
| --- | ---: | ---: | ---: |
| 민수 (1차 결제) | 28,067 | 14,400 | 42,467 |
| 지영 (2차 결제) | 19,900 | 14,333 | 34,233 |
| 서준 | 16,400 | 0 | 16,400 |
| 하은 | 18,400 | 0 | 18,400 |
| 도윤 | 36,300 | 14,400 | 50,700 |

송금: 지영→민수 5,500 · 서준→민수 16,400 · 하은→민수 18,400 · 도윤→민수 36,300 · 도윤→지영 14,400

확인할 점: 서준·하은은 술값 0원이고 2차도 0원입니다. 사이다 2,000원은 하은만 냅니다. 2차는 참석자 전원이 술을 마셨으므로, 음식·술·개인 주문을 구분하지 않고 43,000원 전체를 3명이 전원 N빵합니다.

### N2 · 모두 끝까지 함께

```text
GATHER-0930 정산해 줘. 다섯 명 모두 2차까지 있었고 다 같이 마셨어.
```

기대 결과: 모두 1차 23,800 + 2차 8,600 = **32,400원**. 전원 음주 차수는 음식·술·개인 주문까지 차수 총액 전체를 N빵합니다.
송금: 지영→민수 15,200 · 서준·하은·도윤 → 민수 23,800씩 · 서준·하은·도윤 → 지영 8,600씩

확인할 점: N1과 같은 영수증인데 문장만 바뀌어도 결과가 달라집니다. 발표에서 N1과 나란히 보여 주세요.

### N4 · 차수마다 참석자가 다른 전원 음주

```text
GATHER-0930 정산해 줘. 다섯 명 모두 1차에서 술 마셨고,
2차는 민수·지영·도윤만 끝까지 같이 마셨어.
```

기대 결과: 1차 119,000원은 5명에게 23,800원씩, 2차 43,000원은 3명에게 약 14,300원씩 배분합니다. 각 차수에서 **그 차수의 참석자 전원이 음주한 경우에만** 전체 N빵이 적용됩니다.

### N5 · 중간 귀가가 있는 전원 음주

```text
GATHER-0930 정산해 줘. 1차는 다섯 명 모두 술 마셨고,
서준이랑 하은이는 2차 전에 갔어.
```

확인할 점: N4와 같은 계산 구조지만, 자연어에서 `2차 전에 갔어`를 참석 차수 정보로 해석하는 시나리오입니다. 참석자가 불명확하면 계산하지 않고 I4처럼 추가 정보를 요청해야 합니다.

### I4 · 2차 참석자가 불명확

```text
GATHER-0930 정산해 줘. 1차는 다 같이 있었고 2차는 몇 명만 더 있었어.
```

기대 결과: `누가 2차에 있었는지`가 없으므로 `needs_information`으로 멈추고, 이름을 확인한 뒤에만 N빵을 계산합니다.

### N3 · 주말 스터디 뒤풀이

```text
GATHER-1003 정산해 줘. 태윤이는 운전해서 술 안 마셨고 카페는 안 갔어.
콜라는 태윤이 거야. 민지는 조금 먹었어.
```

| 이름 | 1차 | 2차 | 합계 |
| --- | ---: | ---: | ---: |
| 수아 (1차 결제) | 27,143 | 7,000 | 34,143 |
| 준호 (2차 결제) | 27,200 | 7,000 | 34,200 |
| 민지 | 18,600 | 7,000 | 25,600 |
| 태윤 | 20,200 | 0 | 20,200 |

송금: 준호→수아 20,200 · 민지→수아 18,600 · 태윤→수아 20,200 · 민지→준호 7,000

확인할 점: 와인 30,000원은 태윤을 뺀 3명이 10,000원씩 냅니다. 2차는 참석자 3명 모두 음주했으므로 21,000원 전체를 7,000원씩 N빵합니다. 태윤의 1차 금액은 음식 몫 17,143원에 콜라 3,000원을 더해 100원 단위로 올린 값입니다. 반올림으로 남는 143원은 결제자 몫입니다.

---

## 정보 부족 (추측하지 않고 되묻기)

### I1 · 모임 번호 없음

`어제 회식비 공정하게 나눠 줘.`
Python이 LLM을 부르기 전에 `GATHER-번호`를 찾고, 없으면 바로 되묻습니다. **LLM 0회**라서 Swagger에서 가장 먼저 해 보기 좋습니다.

### I2 · 멤버가 아닌 이름

`GATHER-0930 정산해 줘. 은비도 2차에 잠깐 왔어.`
situation_agent가 `missing_information`에 "은비는 멤버가 아닙니다"를 적으면 분류와 계산을 하지 않고 멈춥니다.
LLM이 은비를 people에 넣으면 Python Guard가 "멤버 불일치"로 막습니다. 어느 쪽이든 은비가 금액에 들어가지 않습니다.

### I3 · 결제자가 멤버가 아님

`GATHER-1002 정산해 줘. 셋 다 술 마셨어.`
영수증 결제자가 "동아리회비카드"라서 누구에게 송금해야 할지 정할 수 없습니다. situation Guard가 `needs_information`으로 멈춥니다.
생각해 볼 점: 회비로 낸 돈은 나눌 필요가 없는지, 총무에게 보내야 하는지는 사람이 정할 일입니다.

---

## 사람 확인

### A1 · 영수증 합계 불일치

`GATHER-1001 정산해 줘. 다들 술 마셨어.`
판독 불가 줄 때문에 메뉴 합계 57,000원과 인쇄 합계 60,000원이 다릅니다.
receipt Guard가 **"차이 3,000원"과 판독 불가 줄**을 알려 주고 `needs_attention`으로 멈춥니다.
LLM에게 합계를 맞추라고 다시 시키지 않는 이유: 없는 메뉴나 금액을 지어낼 수 있기 때문입니다.

---

## 실패와 차단 (자동 테스트로 재현)

| ID | 가짜 LLM 응답 | Python이 막는 코드 | 기대 |
| --- | --- | --- | --- |
| F1 | Supervisor 첫 선택이 `classifier_agent` | `split_settlement_flow()`의 `selected != expected` | blocked · invalid_transition |
| F2 | 삼겹살 금액 70,000 (원문에 없음) | `verify_worker()` receipt: 원문 대조 | failed · "원문에 없는 금액" |
| F3 | 분류 결과에서 생맥주 누락 | `verify_worker()` classifier: 메뉴 집합 비교 | failed · 계산 안 함 |
| F4 | 후라이드치킨 personal, owner=서준 (2차 불참) | `verify_worker()` classifier: owner 참석 확인 | failed |
| F5 | Supervisor Provider 오류 | Supervisor 결과 None | failed · supervisor_failed |
| F6 | GATHER-9999 | `get_receipt` success=false | failed · "찾을 수 없습니다" |

## 부분 실패 (정산은 보여 줌)

| ID | 상황 | 기대 |
| --- | --- | --- |
| P1 | 설명에 "대략 15,000원" (계산 결과에 없는 금액) | explainer Guard가 버림 → **partial**, 송금표는 그대로 |
| P2 | 설명 Agent 시간 초과 | 결과 없음 → **partial**, 송금표는 그대로 |

---

## 발표 데모 순서 (약 7분)

| 순서 | 시나리오 | 보여 줄 것 | 개념 |
| --- | --- | --- | --- |
| 1 | Swagger `tools-preview/GATHER-0930` | Mock Tool 3개, `source: mock:...` | Tool 추가 (LLM 0회) |
| 2 | I1 | 모임 번호 없으면 LLM 전에 되묻기 | Python Guard |
| 3 | N1 | Trace: Supervisor → Worker 번갈아 실행, `python_calculator` 단계 | Supervisor–Worker, 결정적 계산 |
| 4 | N2 | 같은 영수증, 다른 문장 → 다른 금액 | 공정성 |
| 5 | A1 | 합계 불일치를 사람에게 넘김 | 추측 금지, 사람 확인 |
| 6 | I2 | 멤버가 아닌 이름은 금액에 안 들어감 | 정보 부족 |
| 7 | 테스트 F1·P1 | 순서 위반 차단, 설명 실패해도 결과 유지 | 전이 검사, 필수·선택 Worker |

## 실제 LLM으로 돌릴 때 주의

- N1~N3의 금액은 **Worker가 문장을 기대대로 해석했을 때** 값입니다. 다르게 나오면 Trace에서 `situation_agent`의 `people`과 `classifier_agent`의 `items`를 먼저 보세요. 계산 자체는 Python이라 같은 입력이면 항상 같은 결과입니다.
- classifier_agent는 Llama(Ollama)를 씁니다. `docker exec aidevs-ollama ollama list`로 `llama3.2`가 있는지 먼저 확인하세요.
- explainer_agent(Gemma)가 실패해도 결과는 `partial`로 나옵니다. 오류가 아니라 설계한 동작입니다.
