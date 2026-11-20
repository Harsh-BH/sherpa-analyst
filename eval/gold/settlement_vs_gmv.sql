-- Why doesn't the settled amount match GMV for the last 7 days?  -> reconciliation values
-- gap = txn_gmv - settled_net = (txn_gmv - cycle_gmv) + (cycle_gmv - gross) + refunds + fees
WITH v AS (SELECT as_of FROM analytics.data_version),
txn AS (
  SELECT sum(t.amount_paise) FILTER (WHERE t.txn_date BETWEEN v.as_of - 6 AND v.as_of) / 100.0 AS by_date,
         sum(t.amount_paise) FILTER (WHERE t.cycle_date BETWEEN v.as_of - 6 AND v.as_of) / 100.0 AS by_cycle
  FROM analytics.transactions AS t
  JOIN v ON t.txn_date BETWEEN v.as_of - 7 AND v.as_of
  WHERE t.status = 'SUCCESS'
),
st AS (
  SELECT sum(s.gross_paise) / 100.0 AS gross, sum(s.refund_paise) / 100.0 AS refunds,
         sum(s.fee_paise) / 100.0 AS fees, sum(s.net_paise) / 100.0 AS net
  FROM analytics.settlements AS s
  JOIN v ON s.cycle_date BETWEEN v.as_of - 6 AND v.as_of
)
SELECT txn.by_date AS txn_gmv_inr,
       st.net AS settled_net_inr,
       txn.by_date - st.net AS gap_inr,
       txn.by_date - txn.by_cycle AS cutoff_timing,
       txn.by_cycle - st.gross AS missing_transactions,
       st.refunds AS refunds,
       st.fees AS fees
FROM txn CROSS JOIN st
