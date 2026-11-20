-- Daily technical decline rate over the last 30 days  -> trend rows: bucket (YYYY-MM-DD), value, den
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT CAST(t.txn_date AS text) AS bucket,
       CAST(count(*) FILTER (WHERE t.status = 'FAILED' AND t.decline_type = 'TECHNICAL') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date BETWEEN v.as_of - 29 AND v.as_of
GROUP BY t.txn_date
