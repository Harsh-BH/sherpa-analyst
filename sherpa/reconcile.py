"""Why GMV (transactions) and payouts (settlements) disagree for a window.

Pure pandas in, ReconResult out (docs/CONTRACTS.md §3). Identity, asserted:
    gap = txn_gmv - settled_net
        = (txn_gmv - cycle_gmv)          cutoff_timing: the 23:00 IST cycle cutoff moves late sales
        + (cycle_gmv - settled_gross)    missing_transactions: negative = settled sales we never ingested
        + refunds + fees
        + unexplained                    float residue (or net != gross - refund - fee in the data)
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .contracts import ReconComponent, ReconResult, TimeWindow, format_value

SOURCE_OF_TRUTH = ("Money paid out: analytics.settlements (by settlement cycle). "
                   "Sales: analytics.transactions (by IST calendar date).")


def _d(x) -> str:
    return f"{x.day} {x:%b}"


def _inr(x: float) -> str:
    return format_value(abs(x), "inr")


def reconcile(by_txn_date: pd.DataFrame, by_cycle_date: pd.DataFrame, settlements: pd.DataFrame,
              *, window: TimeWindow) -> ReconResult:
    txn_gmv = float(by_txn_date["gmv_inr"].sum())
    cycle_gmv = float(by_cycle_date["gmv_inr"].sum())
    gross, refunds, fees, net = (float(settlements[c].sum()) for c in ("gross_inr", "refund_inr", "fee_inr", "net_inr"))
    gap = txn_gmv - net
    timing, missing = txn_gmv - cycle_gmv, cycle_gmv - gross
    unexplained = gap - (timing + missing + refunds + fees)

    if abs(missing) < 1:
        missing_note = "Every sale in these settlement cycles appears in settlements."
    elif missing < 0:
        missing_note = (f"Settlements include {_inr(missing)} of sales that never reached the transaction data "
                        f"(lost in ingestion); settlements are built from the processor's own records.")
    else:
        missing_note = f"{_inr(missing)} of sales in the transaction data are not in settlements yet."
    components = [
        ReconComponent(name="cutoff_timing", amount_inr=timing, note=(
            f"Sales after 23:00 IST on {_d(window.end)} settle in the next cycle, outside this window, while "
            f"sales after 23:00 IST on {_d(window.start - timedelta(days=1))} settle in its first cycle.")),
        ReconComponent(name="missing_transactions", amount_inr=missing, note=missing_note),
        ReconComponent(name="refunds", amount_inr=refunds, note=f"Refunds of {_inr(refunds)} were netted off the payouts."),
        ReconComponent(name="fees", amount_inr=fees, note=(
            f"MDR fees of {_inr(fees)} ({fees / gross:.2%} of settled gross) were deducted from the payouts."
            if gross else f"MDR fees of {_inr(fees)} were deducted from the payouts.")),
        ReconComponent(name="unexplained", amount_inr=unexplained, note=(
            "Rounding only." if abs(unexplained) < 1 else
            f"{_inr(unexplained)} is not explained by timing, missing sales, refunds or fees: payouts do not "
            f"equal gross - refunds - fees.")),
    ]
    assert abs(sum(c.amount_inr for c in components) - gap) <= 1e-6 * max(1.0, abs(gap)), "recon identity broken"
    return ReconResult(window=window.label or f"{window.start} to {window.end}", txn_gmv_inr=txn_gmv,
                       settled_net_inr=net, gap_inr=gap, components=components, source_of_truth=SOURCE_OF_TRUTH)
