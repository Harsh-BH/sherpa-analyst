-- What was our success rate in the last 7 days?  -> metric evidence: value, num, den
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status = 'SUCCESS') AS num,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date BETWEEN v.as_of - 6 AND v.as_of
