-- Success rate by payment method last week (last 7 days)  -> breakdown rows: segment, value, den
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT t.payment_method AS segment,
       CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date BETWEEN v.as_of - 6 AND v.as_of
GROUP BY t.payment_method
