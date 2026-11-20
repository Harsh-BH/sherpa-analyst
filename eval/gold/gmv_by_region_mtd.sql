-- GMV by region, month to date  -> breakdown rows: segment, value (INR), den (successful payments)
WITH v AS (SELECT as_of, CAST(date_trunc('month', as_of) AS date) AS month_start FROM analytics.data_version)
SELECT t.region AS segment,
       sum(t.amount_paise) FILTER (WHERE t.status = 'SUCCESS') / 100.0 AS value,
       count(*) FILTER (WHERE t.status = 'SUCCESS') AS den
FROM analytics.transactions AS t
JOIN v ON t.txn_date BETWEEN v.month_start AND v.as_of
GROUP BY t.region
