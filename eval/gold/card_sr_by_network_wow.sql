-- Card success rate by network, last 7 days vs the 7 before  -> comparison rows: segment, r0, r1, delta, n0, n1
WITH v AS (SELECT as_of FROM analytics.data_version),
p AS (
  SELECT COALESCE(t.card_network, '(none)') AS segment,
         CASE WHEN t.txn_date >= v.as_of - 6 THEN 1 ELSE 0 END AS cur,
         count(*) FILTER (WHERE t.status = 'SUCCESS') AS s,
         count(*) FILTER (WHERE t.status IN ('SUCCESS', 'FAILED')) AS n
  FROM analytics.transactions AS t
  JOIN v ON t.txn_date BETWEEN v.as_of - 13 AND v.as_of
  WHERE t.payment_method = 'CARD'
  GROUP BY 1, 2
)
SELECT b.segment,
       CAST(b.s AS numeric) / NULLIF(b.n, 0) AS r0,
       CAST(c.s AS numeric) / NULLIF(c.n, 0) AS r1,
       CAST(c.s AS numeric) / NULLIF(c.n, 0) - CAST(b.s AS numeric) / NULLIF(b.n, 0) AS delta,
       b.n AS n0, c.n AS n1
FROM p AS b JOIN p AS c ON b.segment = c.segment AND b.cur = 0 AND c.cur = 1
