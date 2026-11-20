-- Rebuild analytics.* from raw.* (truncate and reload; idempotent).
-- gen/generate.py runs this in its load transaction after set_config('sherpa.version' / 'sherpa.seed');
-- running it without those settings fails on purpose rather than writing an anonymous data_version.
-- Times: created_at is timestamptz; every *_date / *_hour column is Asia/Kolkata.

TRUNCATE analytics.banks, analytics.merchants, analytics.transactions, analytics.settlements,
         analytics.dq_daily, analytics.data_version;

INSERT INTO analytics.banks (bank_id, name, bank_type)
SELECT bank_id, name, bank_type FROM raw.banks;

INSERT INTO analytics.merchants (merchant_id, display_name, mcc, category, city, city_tier, region, onboarded_on)
SELECT merchant_id, display_name, mcc, category, city, city_tier, region, onboarded_on FROM raw.merchants;

-- Latest ingested event per txn_id (retried webhooks), merchant attributes denormalised.
-- LEFT JOIN on purpose: an event with an unknown merchant fails the NOT NULL on region instead of vanishing.
INSERT INTO analytics.transactions (
    txn_id, merchant_id, region, merchant_category, city_tier, created_at, txn_date, txn_hour, cycle_date,
    amount_paise, payment_method, card_network, issuer_bank_id, gateway, device, status, decline_type,
    decline_code, attempt_no)
SELECT e.txn_id, e.merchant_id, m.region, m.category, m.city_tier, e.created_at,
       (e.created_at AT TIME ZONE 'Asia/Kolkata')::date,
       extract(hour FROM e.created_at AT TIME ZONE 'Asia/Kolkata')::smallint,
       ((e.created_at + interval '1 hour') AT TIME ZONE 'Asia/Kolkata')::date,   -- 23:00 IST cutoff
       e.amount_paise, e.payment_method, e.card_network, e.issuer_bank_id, e.gateway, e.device, e.status,
       e.decline_type, e.decline_code, e.attempt_no
FROM (SELECT DISTINCT ON (txn_id) *
      FROM raw.transaction_events
      ORDER BY txn_id, ingested_at DESC, event_id DESC) e
LEFT JOIN raw.merchants m USING (merchant_id);

INSERT INTO analytics.settlements (
    settlement_id, merchant_id, region, cycle_date, settlement_date, txn_count, gross_paise, refund_paise,
    fee_paise, net_paise, utr, status)
SELECT s.settlement_id, s.merchant_id, m.region, s.cycle_date, s.settlement_date, s.txn_count, s.gross_paise,
       s.refund_paise, s.fee_paise, s.net_paise, s.utr, s.status
FROM raw.settlements s
LEFT JOIN raw.merchants m USING (merchant_id);

-- Ingestion health per IST day x region x gateway, from the raw events personas cannot see.
INSERT INTO analytics.dq_daily (
    txn_date, region, gateway, raw_events, distinct_txns, duplicate_events, null_issuer_nonwallet, max_ingest_lag_s)
SELECT (e.created_at AT TIME ZONE 'Asia/Kolkata')::date, m.region, e.gateway,
       count(*), count(DISTINCT e.txn_id), count(*) - count(DISTINCT e.txn_id),
       count(DISTINCT e.txn_id) FILTER (WHERE e.issuer_bank_id IS NULL AND e.payment_method <> 'WALLET'),
       ceil(max(extract(epoch FROM e.ingested_at - e.created_at)))::integer
FROM raw.transaction_events e
LEFT JOIN raw.merchants m USING (merchant_id)
GROUP BY 1, 2, 3;

INSERT INTO analytics.data_version (version, seed, data_start, as_of, generated_at, row_count)
SELECT current_setting('sherpa.version'), current_setting('sherpa.seed')::integer,
       min(txn_date), max(txn_date), now(), count(*)
FROM analytics.transactions;

ANALYZE analytics.banks, analytics.merchants, analytics.transactions, analytics.settlements,
        analytics.dq_daily, analytics.data_version;
