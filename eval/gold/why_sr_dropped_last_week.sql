-- Why did success rate drop last week? (last 7 days vs the 7 before)  -> comparison: r0, r1, delta
WITH v AS (SELECT as_of FROM analytics.data_version),
p AS (
  SELECT CASE WHEN t.txn_date >= v.as_of - 6 THEN 1 ELSE 0 END AS cur,
         CAST(count(*) FILTER (WHERE t.status = 'SUCCESS') AS numeric)
           / NULLIF(count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')), 0) AS sr
  FROM analytics.transactions AS t
  JOIN v ON t.txn_date BETWEEN v.as_of - 13 AND v.as_of
  GROUP BY 1
)
SELECT b.sr AS r0, c.sr AS r1, c.sr - b.sr AS delta
FROM p AS b JOIN p AS c ON b.cur = 0 AND c.cur = 1
