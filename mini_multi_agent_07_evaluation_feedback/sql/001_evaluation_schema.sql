CREATE SCHEMA IF NOT EXISTS mini_multi_agent_07;

CREATE TABLE IF NOT EXISTS mini_multi_agent_07.evaluation_criteria (
    criterion_key TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    required_text TEXT NOT NULL,
    weight INTEGER NOT NULL CHECK (weight > 0),
    mandatory BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS mini_multi_agent_07.evaluation_runs (
    run_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_text TEXT NOT NULL,
    status TEXT NOT NULL,
    final_score INTEGER,
    final_content TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mini_multi_agent_07.evaluation_rounds (
    round_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES mini_multi_agent_07.evaluation_runs(run_id),
    round_number INTEGER NOT NULL,
    draft_content TEXT NOT NULL,
    score INTEGER NOT NULL,
    passed BOOLEAN NOT NULL,
    feedback TEXT NOT NULL,
    failed_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, round_number)
);

-- Labs 09~11에서 사용하는 숙소 예약 이력입니다.
-- 예약 MCP 역할 서버가 이 테이블에 예약 결과를 저장하고,
-- Backend는 이 테이블을 조회해 사용자의 예약 내역을 보여 줍니다.
CREATE TABLE IF NOT EXISTS mini_multi_agent_07.booking_records (
    booking_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    selected_place TEXT NOT NULL,
    hotel_id TEXT NOT NULL,
    hotel_name TEXT NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    guest_count INTEGER NOT NULL CHECK (guest_count > 0),
    total_budget INTEGER NOT NULL DEFAULT 0,
    travel_guide JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_approved_at TIMESTAMPTZ,
    booking_approved_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'confirmed',
    booking_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 이미 07을 실행한 PC에서도 기존 예약을 지우지 않고 새 컬럼만 추가합니다.
ALTER TABLE mini_multi_agent_07.booking_records
    ADD COLUMN IF NOT EXISTS total_budget INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS travel_guide JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS plan_approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS booking_approved_at TIMESTAMPTZ;

-- 같은 run_id의 재시도는 하나의 예약만 만들도록 DB에서도 멱등성을 보장합니다.
CREATE UNIQUE INDEX IF NOT EXISTS booking_records_run_id_unique
    ON mini_multi_agent_07.booking_records (run_id);

INSERT INTO mini_multi_agent_07.evaluation_criteria
    (criterion_key, description, required_text, weight, mandatory)
VALUES
    ('approval_boundary', '승인 전 결제 금지 안내', '승인 전에는 결제를 실행하지 않습니다.', 40, TRUE),
    ('budget_notice', '예산은 예상 금액임을 안내', '예상 금액', 20, TRUE),
    ('source_notice', '외부 정보는 변동될 수 있음을 안내', '변동될 수 있습니다', 20, TRUE),
    ('next_action', '사용자가 다음 행동을 이해할 수 있음', '확인해 주세요', 20, FALSE)
ON CONFLICT (criterion_key) DO UPDATE SET
    description = EXCLUDED.description,
    required_text = EXCLUDED.required_text,
    weight = EXCLUDED.weight,
    mandatory = EXCLUDED.mandatory,
    active = TRUE;
