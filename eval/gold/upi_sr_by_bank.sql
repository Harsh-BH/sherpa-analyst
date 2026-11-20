-- UPI success rate by issuer bank over the last 14 days  -> breakdown rows: segment, value, den
WITH v AS (SELECT as_of FROM analytics.data_version)
SELECT COALESCE(t.issuer_bank_id, '(none)') AS segment,
       CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
         / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS value,
       count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date BETWEEN v.as_of - 13 AND v.as_of
WHERE t.payment_method = 'UPI'
GROUP BY 1
