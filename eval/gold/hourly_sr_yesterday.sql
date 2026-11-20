-- Hourly success rate yesterday (as_of)  -> trend rows: bucket (YYYY-MM-DD HH:00), value, den
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT CAST(t.txn_date AS text) || ' ' || CASE WHEN t.txn_hour < 10 THEN '0' ELSE '' END
         || CAST(t.txn_hour AS text) || ':00' AS bucket,
       CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date = v.as_of
GROUP BY t.txn_date, t.txn_hour
