-- Sherpa schema. CONTRACT: these column names are referenced by sherpa/catalog.yaml,
-- db/access.yaml and code. Owner: master. Change only through docs/CONTRACTS.md.
--
--   raw.*        data as ingested: duplicate webhook events, gaps. No persona can read it.
--   analytics.*  cleaned tables personas query (region-scoped by RLS, column grants from access.yaml).
--   app.*        the app's own writes (run log). Only sherpa_app can touch it.
--
-- Grants, roles and RLS policies are NOT here: db/roles.py generates them from db/access.yaml.
-- Times: created_at is timestamptz; every *_date / *_hour column is Asia/Kolkata (IST).

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS app;

-- ---------------------------------------------------------------- raw
CREATE TABLE IF NOT EXISTS raw.banks (
    bank_id    text PRIMARY KEY,           -- 'KESTREL'
    name       text NOT NULL,              -- 'Kestrel Bank' (fictional)
    bank_type  text NOT NULL               -- 'public' | 'private' | 'small_finance' | 'payments'
);

CREATE TABLE IF NOT EXISTS raw.merchants (
    merchant_id   text PRIMARY KEY,        -- 'M00001'
    display_name  text NOT NULL,           -- UNTRUSTED free text (S6 plants a prompt injection here)
    mcc           text NOT NULL,
    category      text NOT NULL,
    city          text NOT NULL,
    city_tier     text NOT NULL,           -- 'T1' | 'T2' | 'T3'
    region        text NOT NULL,           -- 'North' | 'South' | 'East' | 'West'
    onboarded_on  date NOT NULL
);

-- One row per gateway webhook event. A txn_id can appear more than once (retried webhooks).
CREATE TABLE IF NOT EXISTS raw.transaction_events (
    event_id        bigint PRIMARY KEY,
    txn_id          text NOT NULL,
    merchant_id     text NOT NULL,
    created_at      timestamptz NOT NULL,
    amount_paise    bigint NOT NULL CHECK (amount_paise > 0),
    payment_method  text NOT NULL CHECK (payment_method IN ('UPI', 'CARD', 'NETBANKING', 'WALLET')),
    card_network    text CHECK (card_network IN ('VISA', 'MASTERCARD', 'RUPAY')),   -- NULL unless CARD
    issuer_bank_id  text,                                                           -- payer's bank; NULL for WALLET
    gateway         text NOT NULL CHECK (gateway IN ('PG_A', 'PG_B', 'PG_C')),
    device          text NOT NULL CHECK (device IN ('android', 'ios', 'web', 'pos')),
    status          text NOT NULL CHECK (status IN ('SUCCESS', 'FAILED', 'DROPPED')), -- DROPPED = user abandoned
    decline_type    text CHECK (decline_type IN ('TECHNICAL', 'BUSINESS')),          -- NULL unless FAILED
    decline_code    text,                                                           -- NULL unless FAILED
    attempt_no      smallint NOT NULL DEFAULT 1,
    ingested_at     timestamptz NOT NULL
);

-- One row per merchant per settlement cycle. Cycle D = sales from D-1 23:00 IST to D 22:59:59 IST,
-- paid out T+1 (settlement_date = cycle_date + 1). Generated from the TRUE transactions, so it
-- still contains sales whose events were lost in ingestion (S5).
CREATE TABLE IF NOT EXISTS raw.settlements (
    settlement_id    text PRIMARY KEY,
    merchant_id      text NOT NULL,
    cycle_date       date NOT NULL,
    settlement_date  date NOT NULL,
    txn_count        integer NOT NULL,
    gross_paise      bigint NOT NULL,      -- sum of successful sales in the cycle
    refund_paise     bigint NOT NULL,      -- refunds netted off in this payout
    fee_paise        bigint NOT NULL,      -- MDR
    net_paise        bigint NOT NULL,      -- gross - refund - fee
    utr              text NOT NULL,
    status           text NOT NULL CHECK (status IN ('SETTLED', 'PENDING'))
);

-- ---------------------------------------------------------------- analytics
CREATE TABLE IF NOT EXISTS analytics.banks (
    bank_id    text PRIMARY KEY,
    name       text NOT NULL,
    bank_type  text NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.merchants (
    merchant_id   text PRIMARY KEY,
    display_name  text NOT NULL,
    mcc           text NOT NULL,
    category      text NOT NULL,
    city          text NOT NULL,
    city_tier     text NOT NULL,
    region        text NOT NULL,
    onboarded_on  date NOT NULL
);

-- Deduplicated (latest ingested event per txn_id), merchant attributes denormalised.
CREATE TABLE IF NOT EXISTS analytics.transactions (
    txn_id             text PRIMARY KEY,
    merchant_id        text NOT NULL,
    region             text NOT NULL,
    merchant_category  text NOT NULL,
    city_tier          text NOT NULL,
    created_at         timestamptz NOT NULL,
    txn_date           date NOT NULL,      -- IST calendar date of created_at
    txn_hour           smallint NOT NULL,  -- IST hour 0-23
    cycle_date         date NOT NULL,      -- settlement cycle: IST date of (created_at + 1 hour)
    amount_paise       bigint NOT NULL,
    payment_method     text NOT NULL,
    card_network       text,
    issuer_bank_id     text,
    gateway            text NOT NULL,
    device             text NOT NULL,
    status             text NOT NULL,
    decline_type       text,
    decline_code       text,
    attempt_no         smallint NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_txn_date_idx   ON analytics.transactions (txn_date);
CREATE INDEX IF NOT EXISTS transactions_cycle_date_idx ON analytics.transactions (cycle_date);

CREATE TABLE IF NOT EXISTS analytics.settlements (
    settlement_id    text PRIMARY KEY,
    merchant_id      text NOT NULL,
    region           text NOT NULL,
    cycle_date       date NOT NULL,
    settlement_date  date NOT NULL,
    txn_count        integer NOT NULL,
    gross_paise      bigint NOT NULL,
    refund_paise     bigint NOT NULL,
    fee_paise        bigint NOT NULL,
    net_paise        bigint NOT NULL,
    utr              text NOT NULL,
    status           text NOT NULL
);
CREATE INDEX IF NOT EXISTS settlements_cycle_date_idx ON analytics.settlements (cycle_date);

-- Ingestion health per IST day x region x gateway, computed from raw.* (personas cannot see raw).
CREATE TABLE IF NOT EXISTS analytics.dq_daily (
    txn_date               date NOT NULL,
    region                 text NOT NULL,
    gateway                text NOT NULL,
    raw_events             bigint NOT NULL,
    distinct_txns          bigint NOT NULL,
    duplicate_events       bigint NOT NULL,  -- raw_events - distinct_txns
    null_issuer_nonwallet  bigint NOT NULL,  -- issuer_bank_id NULL on a non-WALLET txn
    max_ingest_lag_s       integer NOT NULL,
    PRIMARY KEY (txn_date, region, gateway)
);

-- Exactly one row. as_of = last complete IST date in the data; "today" for every relative window.
CREATE TABLE IF NOT EXISTS analytics.data_version (
    version       text PRIMARY KEY,
    seed          integer NOT NULL,
    data_start    date NOT NULL,
    as_of         date NOT NULL,
    generated_at  timestamptz NOT NULL,
    row_count     bigint NOT NULL
);

-- ---------------------------------------------------------------- app
CREATE TABLE IF NOT EXISTS app.runs (
    run_id        text PRIMARY KEY,
    asked_at      timestamptz NOT NULL DEFAULT now(),
    persona       text NOT NULL,
    question      text NOT NULL,
    status        text NOT NULL,
    route         text,
    plan          jsonb,
    sql           text[],
    evidence      jsonb,
    claims        jsonb,
    confidence    text,
    data_version  text,
    timings_ms    jsonb,
    llm_usage     jsonb,
    error         text,
    source        text NOT NULL DEFAULT 'app',  -- app | test | eval (SHERPA_RUN_SOURCE); the Runs page reads 'app' only
    bundle        jsonb                         -- the whole AnswerBundle: history and permalinks reopen it
);
ALTER TABLE app.runs ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'app';   -- databases created before it
ALTER TABLE app.runs ADD COLUMN IF NOT EXISTS bundle jsonb;

-- Thumbs up/down on a run. Insert-only (the app role has no UPDATE): the latest row per run wins when read.
CREATE TABLE IF NOT EXISTS app.run_feedback (
    run_id   text NOT NULL,
    persona  text NOT NULL,
    rating   smallint NOT NULL CHECK (rating IN (-1, 1)),
    at       timestamptz NOT NULL DEFAULT now()
);
