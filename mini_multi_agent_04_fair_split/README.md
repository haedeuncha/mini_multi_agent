# Mini Multi-Agent 04 · Fair Split (공정 N빵 계산기)

회식이나 모임 비용을 **공정하게** 나누는 계산기입니다.
술 안 마신 사람, 많이 먹은 사람, 1차만 있다 간 사람을 모두 반영합니다.

지금 단계는 **계산 규칙(Python Guard에 해당하는 결정적 계산)**만 완성한 상태입니다.
다음 단계에서 01~03강의 패턴으로 멀티 에이전트를 붙입니다.

## 바로 실행하기

- 화면: `web/index.html`을 브라우저로 열면 됩니다. 설치할 것이 없습니다.
- 테스트: `node tests/test_calc.js`, `node tests/test_scenarios.js`
- 계획서: `docs/PLAN.md` · 시나리오: `docs/SCENARIOS.md`

## 나누는 규칙

| 구분 | 누가 내나 | 예시 |
| --- | --- | --- |
| 먹은 양 | 그 차수 참석자가 적게 0.5 · 보통 1 · 많이 1.5 비율로 | 삼겹살, 치킨 |
| 술 | 그 차수에서 술 마신 사람끼리 똑같이 | 소주, 맥주 |
| 다같이 | 그 차수 참석자 모두 똑같이 | 자리값, 기본 안주 |
| 한 사람 | 시킨 사람 혼자 | 사이다, 개인 메뉴 |

- 차수에 없던 사람은 그 차수 금액을 내지 않습니다.
- 받을 돈은 반올림 단위(1·10·100·1,000원)로 올려서 받고, 남는 돈은 결제한 사람 몫입니다.
- 차수마다 결제자가 다르면 서로 주고받을 돈을 상계해서 송금 줄 수를 줄입니다.

## 폴더 구조

```text
mini_multi_agent_04_fair_split/
├─ core/calc.js        # 정산 계산 순수 함수 computeSplit()
├─ web/index.html      # 계산기 화면 (calc.js 내용이 들어 있는 단일 파일)
├─ docs/PLAN.md        # 프로젝트 계획서 (기획 · 요구사항 · Agent · 오케스트레이션 · 일정)
├─ docs/SCENARIOS.md   # 계산 · 멀티 에이전트 · 발표 시나리오
└─ tests/
   ├─ test_calc.js       # 규칙 단위 테스트 7개
   └─ test_scenarios.js  # 시나리오 S1~S8 자동 검사
```

`web/index.html` 안에도 `computeSplit()`이 들어 있습니다. 규칙을 바꾸면 두 곳을 같이 고치세요.

## 다음 단계: 멀티 에이전트로 확장

계산은 지금처럼 코드가 하고, LLM Agent는 **입력을 채우고 설명하는 일**만 맡깁니다.
02강의 "숫자 계산은 LLM에 맡기지 않는다" 원칙과 같습니다.

```text
사용자 입력 (영수증 사진 / "민수는 술 안 마셨고 도윤이 많이 먹었어")
 ├→ Receipt Agent   : 영수증에서 메뉴·금액 추출
 └→ Situation Agent : 문장에서 참석·음주·먹은 양 추출      (Parallel)
        ↓ Contract 검증 (금액 합계 = 영수증 총액인지)
 → Classifier Agent : 메뉴를 먹은 양 / 술 / 다같이 / 한 사람으로 분류
 → computeSplit()   : 결정적 계산 (LLM 없음)
 → Explainer Agent  : "왜 이 금액인지" 한 사람씩 설명
 → 사용자 확인 후 단톡방 문구 생성 (Human-in-the-loop)
```

| 계획서 개념 | 이 프로젝트에서 |
| --- | --- |
| 역할과 책임 | Receipt · Situation · Classifier · Explainer |
| 입출력 계약 | 추출 금액 합계와 영수증 총액 일치 검사 |
| Parallel + Join | 영수증 추출과 상황 추출을 동시에 |
| 필수·선택 Agent | Receipt·Situation은 필수, Explainer는 선택 |
| Human-in-the-loop | 분류 결과를 사람이 확인한 뒤 확정 |
| Trace | 어떤 Agent가 어떤 값을 채웠는지 기록 |
