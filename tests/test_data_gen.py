"""Generator checks that need no database."""
import numpy as np
import pandas as pd
import pytest

from gen.generate import CARD, FAILED, SUCCESS, UPI, _decompose, build
from sherpa.config import load_catalog


def _period(cells):  # [(method, n, successes)] -> one row per attempt
    return pd.DataFrame({
        "method": np.concatenate([np.full(n, m) for m, n, _ in cells]),
        "status": np.concatenate([np.r_[np.full(s, SUCCESS), np.full(n - s, FAILED)] for _, n, s in cells])})


def test_decompose_matches_the_worked_example():
    # docs/ARCHITECTURE.md: cards 60%->40% at 96.0->96.5%, UPI 40%->60% at 88.0->88.5%: -1.10 = mix -1.60 + rate +0.50
    d = _decompose(_period([(CARD, 600, 576), (UPI, 400, 352)]), _period([(CARD, 400, 386), (UPI, 600, 531)]), "method")
    assert d["delta"] == pytest.approx(-0.011)
    assert d["mix_total"] == pytest.approx(-0.016)
    assert d["rate_total"] == pytest.approx(0.005)
    assert d["simpson"]


@pytest.fixture(scope="module")
def short():
    return build(42, days=3)


def test_build_is_deterministic(short):
    tables, truth = build(42, days=3)
    assert truth == short[1]
    for name, df in tables.items():
        pd.testing.assert_frame_equal(df, short[0][name], check_exact=True)


def test_values_come_from_the_catalog_vocabularies(short):
    tables, _ = short
    ev = tables["transaction_events"]
    for d in load_catalog().dimensions:
        if d.values and d.column in ev and d.dtype == "text":
            got = set(ev[d.column].dropna().astype(str))
            assert got <= set(d.values), (d.name, got - set(d.values))
    assert set(tables["banks"].bank_id) == set(load_catalog().dimension("issuer_bank").values)
    assert set(tables["merchants"].category) == set(load_catalog().dimension("merchant_category").values)
    assert (ev.issuer_bank_id.isna() == (ev.payment_method == "WALLET")).all()
    assert (ev.card_network.notna() == (ev.payment_method == "CARD")).all()
    assert (ev.decline_code.notna() == (ev.status == "FAILED")).all()
    assert not ((ev.decline_code == "ACS_3DS_FAILURE") & (ev.payment_method != "CARD")).any()
    st = tables["settlements"]
    assert (st.net_paise == st.gross_paise - st.refund_paise - st.fee_paise).all()
    assert set(ev.status) <= {"SUCCESS", "FAILED", "DROPPED"}
