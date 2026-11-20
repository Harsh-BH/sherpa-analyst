-- Hourly success rate yesterday (as_of)  -> trend rows: hour (0-23 IST), value, den
-- (hour, not the pipeline's "YYYY-MM-DD HH:00" bucket text, so any correct answer can match)
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT t.txn_hour AS hour,
       CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date = v.as_of
GROUP BY t.txn_hour
