-- Is last week's transaction data complete?  -> one row per data-quality finding: dq_check, gateway, day, n
--   duplicates:   day x gateway with >= 100 duplicate events or >= 0.5% of events (n = duplicate events)
--   missing_data: runs of consecutive hours below 10% of the median of the same hour and gateway over the
--                 7 days before, whose medians sum to >= 20 attempts (day = first hour's date, n = hours)
--   nulls:        non-wallet payments without an issuer bank (n = rows)
WITH v AS (SELECT as_of FROM analytics.data_version),
h AS (
  SELECT t.txn_date, t.txn_hour, t.gateway, count(*) AS attempts
  FROM analytics.transactions AS t
  JOIN v ON t.txn_date BETWEEN v.as_of - 13 AND v.as_of
  GROUP BY 1, 2, 3
),
grid AS (   -- every (day, gateway) from dq_daily x every hour, so hours with no rows count as 0 attempts
  SELECT dg.txn_date, hr.txn_hour, dg.gateway, COALESCE(h.attempts, 0) AS attempts
  FROM (SELECT DISTINCT q.txn_date, q.gateway FROM analytics.dq_daily AS q
        JOIN v ON q.txn_date BETWEEN v.as_of - 13 AND v.as_of) AS dg
  CROSS JOIN (SELECT txn_hour FROM h GROUP BY txn_hour) AS hr
  LEFT JOIN h ON h.txn_date = dg.txn_date AND h.txn_hour = hr.txn_hour AND h.gateway = dg.gateway
),
usual AS (
  SELECT c.txn_date, c.txn_hour, c.gateway, c.attempts,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY p.attempts) AS med
  FROM grid AS c
  JOIN grid AS p ON p.gateway = c.gateway AND p.txn_hour = c.txn_hour
                AND p.txn_date BETWEEN c.txn_date - 7 AND c.txn_date - 1
  JOIN v ON c.txn_date BETWEEN v.as_of - 6 AND v.as_of
  GROUP BY 1, 2, 3, 4
),
cand AS (  -- gaps-and-islands: consecutive candidate hours share idx - row_number()
  SELECT u.*, (u.txn_date - DATE '2000-01-01') * 24 + u.txn_hour
              - row_number() OVER (PARTITION BY u.gateway ORDER BY u.txn_date, u.txn_hour) AS island
  FROM usual AS u WHERE u.med > 0 AND u.attempts < 0.1 * u.med
),
runs AS (
  SELECT gateway, min(txn_date) AS day, count(*) AS hours, sum(med) AS expected
  FROM cand GROUP BY gateway, island
),
dq AS (
  SELECT q.txn_date, q.gateway, sum(q.duplicate_events) AS dup, sum(q.raw_events) AS raw,
         sum(q.null_issuer_nonwallet) AS nulls
  FROM analytics.dq_daily AS q
  JOIN v ON q.txn_date BETWEEN v.as_of - 6 AND v.as_of
  GROUP BY 1, 2
)
SELECT 'missing_data' AS dq_check, gateway, CAST(day AS text) AS day, hours AS n
FROM runs WHERE expected >= 20
UNION ALL
SELECT 'duplicates', gateway, CAST(txn_date AS text), dup
FROM dq WHERE dup > 0 AND (dup >= 100 OR dup >= 0.005 * raw)
UNION ALL
SELECT 'nulls', NULL, NULL, sum(nulls) FROM dq HAVING sum(nulls) > 0
