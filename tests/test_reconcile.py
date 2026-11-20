from datetime import date

import pandas as pd
import pytest

from sherpa.contracts import TimeWindow
from sherpa.reconcile import reconcile

WINDOW = TimeWindow(start=date(2026, 11, 12), end=date(2026, 11, 14), label="12-14 Nov 2026")
DAYS = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)]


def frames(lost: float = 0.0, net_skew: float = 0.0):
    # daily sales 10 L; 40k of each day's sales fall after 23:00 and move to the next cycle
    by_txn = pd.DataFrame({"txn_date": DAYS, "gmv_inr": [1_000_000.0, 1_000_000.0, 1_000_000.0]})
    # cycle D = (D-1 23:00, D 23:00]: the 11 Nov late sales (30k) come in, 14 Nov late sales (40k) go out
    cycle = [1_000_000 - 40_000 + 30_000, 1_000_000, 1_000_000]
    by_cycle = pd.DataFrame({"cycle_date": DAYS, "gmv_inr": cycle})
    gross = [g + (lost if i == 1 else 0) for i, g in enumerate(cycle)]
    refund = [round(g * 0.002, 2) for g in gross]
    fee = [round(g * 0.018, 2) for g in gross]
    net = [g - r - f + (net_skew if i == 0 else 0) for i, (g, r, f) in enumerate(zip(gross, refund, fee))]
    st = pd.DataFrame({"cycle_date": DAYS, "gross_inr": gross, "refund_inr": refund, "fee_inr": fee, "net_inr": net})
    return by_txn, by_cycle, st


def amounts(res):
    return {c.name: c.amount_inr for c in res.components}


def test_identity_and_components():
    res = reconcile(*frames(), window=WINDOW)
    a = amounts(res)
    assert res.txn_gmv_inr == 3_000_000
    assert res.gap_inr == pytest.approx(sum(a.values()), abs=1e-6)
    assert a["cutoff_timing"] == pytest.approx(10_000)        # 40k out - 30k in
    assert a["missing_transactions"] == pytest.approx(0)
    assert a["refunds"] == pytest.approx(0.002 * 2_990_000) and a["fees"] == pytest.approx(0.018 * 2_990_000)
    assert a["unexplained"] == pytest.approx(0, abs=1e-6)
    notes = {c.name: c.note for c in res.components}
    assert "after 23:00 IST on 14 Nov settle in the next cycle" in notes["cutoff_timing"]
    assert "11 Nov" in notes["cutoff_timing"]
    assert "1.80% of settled gross" in notes["fees"]
    assert res.window == "12-14 Nov 2026"


def test_missing_transactions_are_negative():
    res = reconcile(*frames(lost=25_000.0), window=WINDOW)
    a = amounts(res)
    assert a["missing_transactions"] == pytest.approx(-25_000)
    assert "never reached the transaction data" in next(c.note for c in res.components
                                                        if c.name == "missing_transactions")
    assert res.gap_inr == pytest.approx(sum(a.values()), abs=1e-6)


def test_unexplained_residue_is_reported():
    res = reconcile(*frames(net_skew=-500.0), window=WINDOW)
    a = amounts(res)
    assert a["unexplained"] == pytest.approx(500.0)
    assert "not explained" in next(c.note for c in res.components if c.name == "unexplained")
