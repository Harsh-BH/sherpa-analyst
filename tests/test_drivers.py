import re

import numpy as np
import pandas as pd
import pytest

from sherpa.contracts import DimensionDecomposition, SegmentEffect
from sherpa.drivers import NONE_LABEL, decompose, evidence_from_report, explain_change

BANKS = ["KESTREL", "HERON", "OSPREY", "MYNA", "EGRET", "IBIS", "HORNBILL", "BULBUL", "SARUS", "DRONGO"]
DIMS = ["payment_method", "issuer_bank", "card_network", "merchant_category", "region", "device"]


def frame(rows):
    """rows: (segment, period, num, den) -> decompose frame on dimension 'seg'."""
    return pd.DataFrame(rows, columns=["seg", "period", "num", "den"])


def seg(dec, name):
    return next(s for s in dec.segments if s.segment == name)


# ---------------------------------------------------------------- A1 decompose
def test_worked_example():
    df = frame([("CARD", "baseline", 57_600, 60_000), ("UPI", "baseline", 35_200, 40_000),
                ("CARD", "current", 38_600, 40_000), ("UPI", "current", 53_100, 60_000)])
    dec = decompose(df, "seg")
    assert dec.r0 == pytest.approx(0.928, abs=1e-9) and dec.r1 == pytest.approx(0.917, abs=1e-9)
    assert dec.delta == pytest.approx(-0.011, abs=1e-9)
    assert dec.mix_total == pytest.approx(-0.016, abs=1e-9)
    assert dec.rate_total == pytest.approx(0.005, abs=1e-9)
    card, upi = seg(dec, "CARD"), seg(dec, "UPI")
    assert card.mix_effect == pytest.approx(-0.008, abs=1e-9) and upi.mix_effect == pytest.approx(-0.008, abs=1e-9)
    assert card.rate_effect == pytest.approx(0.0025, abs=1e-9) and upi.rate_effect == pytest.approx(0.0025, abs=1e-9)
    # both rates rose (significantly) while the total fell: textbook Simpson
    assert card.significant and upi.significant and card.z > 0 and upi.z > 0
    assert dec.simpson_flag
    assert dec.mix_chi2_p < 1e-12
    assert all(s.supported and s.material for s in dec.segments)


def test_segment_only_in_current_is_pure_mix():
    df = frame([("CARD", "baseline", 9_600, 10_000), ("UPI", "baseline", 8_850, 10_000),
                ("CARD", "current", 9_600, 10_000), ("UPI", "current", 8_850, 10_000),
                ("NEW", "current", 4_000, 5_000)])
    dec = decompose(df, "seg")
    new = seg(dec, "NEW")
    assert new.rate0 is None and new.rate1 == 0.8 and new.n0 == 0 and new.share0 == 0
    assert new.rate_effect == 0 and new.mix_effect < 0 and new.total_effect == new.mix_effect
    assert new.z is None and not new.significant and not new.supported
    assert abs(dec.mix_total + dec.rate_total - dec.delta) < 1e-12
    assert dec.rate_total == pytest.approx(0, abs=1e-15)   # existing segments' rates are unchanged


def test_zero_denominator_segment():
    df = frame([("A", "baseline", 900, 1_000), ("A", "current", 850, 1_000),
                ("B", "baseline", 0, 0), ("B", "current", 0, 0),       # empty in both periods
                ("C", "baseline", 0, 0), ("C", "current", 450, 500)])  # empty in baseline only
    dec = decompose(df, "seg")
    b, c = seg(dec, "B"), seg(dec, "C")
    assert b.rate0 is None and b.rate1 is None and b.total_effect == 0 and b.z is None
    assert c.rate0 is None and c.rate_effect == 0
    assert abs(dec.mix_total + dec.rate_total - dec.delta) < 1e-12
    with pytest.raises(ValueError):
        decompose(frame([("A", "baseline", 0, 0), ("A", "current", 5, 10)]), "seg")


def test_null_dimension_values_get_a_label():
    df = pd.DataFrame({"card_network": ["VISA", None, "VISA", None], "period": ["baseline"] * 2 + ["current"] * 2,
                       "num": [90, 80, 85, 80], "den": [100, 100, 100, 100]})
    assert {s.segment for s in decompose(df, "card_network").segments} == {"VISA", NONE_LABEL}


def test_sum_numerator_gets_no_ztest():
    # avg_ticket_size: num = INR sum, den = successful payments
    df = frame([("UPI", "baseline", 450_000.5, 1_500), ("UPI", "current", 480_000.0, 1_600),
                ("CARD", "baseline", 2_400_000.0, 1_200), ("CARD", "current", 2_000_000.25, 1_000)])
    dec = decompose(df, "seg")
    assert all(s.z is None and s.p_value is None and s.q_value is None and not s.significant for s in dec.segments)
    assert abs(dec.mix_total + dec.rate_total - dec.delta) < 1e-12 * max(1, abs(dec.r0), abs(dec.r1))


def test_identity_holds_on_random_frames():
    rng = np.random.default_rng(20261121)
    for _ in range(200):
        k = int(rng.integers(1, 13))
        rows = []
        for i in range(k):
            for period in ("baseline", "current"):
                if rng.random() < 0.15:          # segment missing from this period
                    continue
                n = int(rng.choice([0, int(rng.integers(1, 200)), int(rng.integers(1, 200_000))]))
                rows.append((f"s{i}", period, int(rng.binomial(n, rng.uniform(0.5, 1.0))) if n else 0, n))
        df = frame(rows)
        tot = df.groupby("period")["den"].sum()
        if len(tot) < 2 or (tot <= 0).any():
            continue
        dec = decompose(df, "seg")
        assert abs(sum(s.mix_effect for s in dec.segments) + sum(s.rate_effect for s in dec.segments)
                   - dec.delta) < 1e-12
        assert sum(s.total_effect for s in dec.segments) == pytest.approx(dec.delta, abs=1e-12)


# ---------------------------------------------------------------- A2 explain_change: ranking
def synthetic_rows(rng, n, period, *, upi=0.45, category=None, region=None, broken_bank=None):
    """Row-level payment attempts. Rate depends on method (+ a small fixed per-bank offset)."""
    method = rng.choice(["UPI", "CARD", "NETBANKING", "WALLET"], n, p=[upi, 0.85 - upi, 0.10, 0.05])
    bank = rng.choice(BANKS, n, p=np.array([18, 14, 12, 11, 10, 9, 8, 7, 6, 5]) / 100).astype(object)
    bank[method == "WALLET"] = None
    network = np.where(method == "CARD", rng.choice(["VISA", "MASTERCARD", "RUPAY"], n, p=[.5, .3, .2]), None)
    cats = ["grocery", "electronics", "fuel", "restaurants", "pharmacy", "apparel", "travel", "utilities"]
    rate = (pd.Series(method).map({"UPI": .885, "CARD": .96, "NETBANKING": .92, "WALLET": .94}).to_numpy()
            + pd.Series(bank).map({b: (i - 4.5) * 0.002 for i, b in enumerate(BANKS)}).fillna(0).to_numpy())
    if broken_bank:
        rate = np.where((bank == broken_bank) & (method == "UPI"), 0.60, rate)
    return pd.DataFrame({
        "payment_method": method, "issuer_bank": bank, "card_network": network,
        "merchant_category": np.full(n, category) if category else rng.choice(cats, n),
        "region": np.full(n, region) if region else rng.choice(["North", "South", "East", "West"], n),
        "device": rng.choice(["android", "ios", "web", "pos"], n, p=[.5, .2, .2, .1]),
        "period": period, "success": rng.random(n) < rate})


def frames_from(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {d: rows.groupby([d, "period"], dropna=False)["success"].agg(num="sum", den="size").reset_index()
            for d in DIMS}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_localised_rate_break_ranks_the_bank_first(seed):
    rng = np.random.default_rng(seed)
    rows = pd.concat([synthetic_rows(rng, 150_000, "baseline"),
                      synthetic_rows(rng, 150_000, "current", broken_bank="HERON")])
    rep = explain_change(frames_from(rows), metric="success_rate", window="w", baseline="b")
    ranked = [d.dimension for d in rep.dimensions]
    assert rep.top_dimension == "issuer_bank" and rep.dimensions[0].segments[0].segment == "HERON"
    # the method HERON serves dips significantly too, yet ranks below the bank
    upi = seg(rep.dimensions[ranked.index("payment_method")], "UPI")
    assert upi.rate_effect < 0 and upi.significant and upi.q_value is not None
    assert ranked.index("issuer_bank") < ranked.index("payment_method")
    assert not rep.simpson_flag
    assert any("agrees on the top segment" in n for n in rep.notes)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_pure_mix_shift_is_flagged_simpson(seed):
    rng = np.random.default_rng(seed)
    rows = pd.concat([synthetic_rows(rng, 150_000, "baseline"), synthetic_rows(rng, 150_000, "current"),
                      # a UPI-heavy grocery merchant in the South onboards: same per-method rates
                      synthetic_rows(rng, 50_000, "current", upi=0.85, category="grocery", region="South")])
    rep = explain_change(frames_from(rows), metric="success_rate", window="w", baseline="b")
    assert rep.delta < 0
    assert rep.top_dimension in ("payment_method", "merchant_category")
    assert rep.simpson_flag
    pm = next(d for d in rep.dimensions if d.dimension == "payment_method")
    assert pm.simpson_flag and abs(pm.mix_total) > abs(rep.delta) * 0.9
    ranked = [d.dimension for d in rep.dimensions]
    assert ranked.index("payment_method") < ranked.index("issuer_bank")


def test_uniform_decline_has_no_top_dimension():
    rng = np.random.default_rng(5)
    cur = synthetic_rows(rng, 150_000, "current")
    cur["success"] &= rng.random(len(cur)) > 0.011      # every rate falls ~1 pp, nowhere in particular
    rows = pd.concat([synthetic_rows(rng, 150_000, "baseline"), cur])
    rep = explain_change(frames_from(rows), metric="success_rate", window="w", baseline="b")
    assert rep.delta < -0.005
    assert rep.top_dimension is None and not rep.simpson_flag
    assert "No dimension explains" in rep.notes[0]


# ---------------------------------------------------------------- A2 drill-down
def issuer_network_cells(break_pp: float) -> pd.DataFrame:
    """Expected-count cells (no sampling noise): HERON x RUPAY cards lose break_pp of success rate."""
    share = {"KESTREL": .4, "HERON": .3, "OSPREY": .3}
    net = {"VISA": .5, "MASTERCARD": .3, "RUPAY": .2}
    rows = []
    for period in ("baseline", "current"):
        for b, sb in share.items():
            for nw, sn in net.items():
                n = round(400_000 * sb * sn)
                r = 0.96 - (break_pp if (period, b, nw) == ("current", "HERON", "RUPAY") else 0)
                rows.append((b, nw, period, round(n * r), n))
    return pd.DataFrame(rows, columns=["issuer_bank", "card_network", "period", "num", "den"])


def test_drilldown_finds_a_break_invisible_at_depth_one():
    cells = issuer_network_cells(0.008)
    frames = {d: cells.groupby([d, "period"], as_index=False)[["num", "den"]].sum()
              for d in ("issuer_bank", "card_network")}
    rep = explain_change(frames, metric="success_rate", window="w", baseline="b",
                         drill={("issuer_bank", "card_network"): cells})
    for d in rep.dimensions:      # depth 1: neither HERON nor RUPAY moves enough to report
        assert not any(s.material and s.significant for s in d.segments), d.dimension
    top = rep.drilldown[0]
    assert top.dims == {"issuer_bank": "HERON", "card_network": "RUPAY"}
    assert top.effect.segment == "issuer_bank=HERON · card_network=RUPAY"
    assert top.effect.significant and top.effect.material and top.effect.q_value < 0.05
    assert top.effect.rate1 - top.effect.rate0 == pytest.approx(-0.008, abs=1e-4)


# ---------------------------------------------------------------- A2 evidence
def test_evidence_keys_and_formats():
    rng = np.random.default_rng(1)
    rows = pd.concat([synthetic_rows(rng, 60_000, "baseline"),
                      synthetic_rows(rng, 60_000, "current", broken_bank="HERON")])
    cells = rows.groupby(["issuer_bank", "card_network", "period"], dropna=False)["success"] \
        .agg(num="sum", den="size").reset_index()
    rep = explain_change(frames_from(rows), metric="success_rate", window="last 7 days", baseline="previous 7 days",
                         drill={("issuer_bank", "card_network"): cells})
    ev = evidence_from_report(rep, start_id=3)
    assert [e.id for e in ev] == ["E3", "E4", "E5", "E6", "E7"]
    assert [e.kind for e in ev] == ["comparison", "decomposition", "decomposition", "decomposition", "drilldown"]
    for e in ev:
        assert all(re.fullmatch(r"[A-Za-z0-9_]+", k) for k in e.values), e.id
        assert set(e.values) == set(e.formats), e.id
        assert e.window == "last 7 days" and e.baseline == "previous 7 days"
    overall = ev[0].values
    assert overall["delta"] == rep.delta and ev[0].formats["delta"] == "pp" and ev[0].formats["r0"] == "pct"
    assert overall["mix_total"] + overall["rate_total"] == pytest.approx(rep.delta, abs=1e-12)
    bank = ev[1]
    assert bank.values["HERON_rate1"] < bank.values["HERON_rate0"] and bank.formats["HERON_share1"] == "pct"
    assert {"segment": NONE_LABEL, "key": "none"}.items() <= next(
        r for r in bank.table if r["segment"] == NONE_LABEL).items()
    drill = ev[-1]
    assert any(k.startswith("HERON_") for k in drill.values)
    assert all({"issuer_bank", "card_network", "key"} <= set(r) for r in drill.table)


# ---------------------------------------------------------------- adversarial review regressions
def test_r18_noise_names_no_driver_and_no_simpson():
    # shares wobble 50/50 -> 50.5/49.5 at flat rates: Δ is all mix, but nothing is significant
    df = frame([("CARD", "baseline", 4_800, 5_000), ("UPI", "baseline", 4_400, 5_000),
                ("CARD", "current", 4_848, 5_050), ("UPI", "current", 4_356, 4_950)])
    dec = decompose(df, "seg")
    assert dec.mix_chi2_p > 0.05 and abs(dec.mix_total - dec.delta) < 1e-12
    assert not dec.simpson_flag                      # mix test not significant
    rep = explain_change({"seg": df}, metric="success_rate", window="w", baseline="b")
    assert rep.top_dimension is None and not rep.simpson_flag
    assert "within noise" in rep.notes[0]


def test_r19_simpson_needs_mix_in_the_direction_of_the_change():
    from sherpa.drivers import _judge
    s = lambda name, rate: SegmentEffect(dimension="X", segment=name, n0=5000, n1=5000, s0=1, s1=1, share0=.5,
                                         share1=.5, rate0=.95, rate1=.95 + rate, mix_effect=0, rate_effect=rate / 2,
                                         total_effect=rate / 2, p_value=0.3, supported=True, significant=False,
                                         material=True)
    dec = DimensionDecomposition(dimension="X", r0=.9, r1=.89875, delta=-0.00125, mix_total=0.00075,
                                 rate_total=-0.002, mix_chi2_p=1e-9, score=0, simpson_flag=False,
                                 segments=[s("A", -0.002), s("B", -0.002)])
    assert not _judge(dec).simpson_flag              # mix pushed up while the rate fell
    dec.mix_total, dec.rate_total = -0.00125, 0.0
    assert _judge(dec).simpson_flag


def test_r20_untested_segments_block_simpson():
    # avg_ticket_size: UPI's ticket falls 500 -> 350 INR while volume shifts to UPI; sums cannot be z-tested
    df = frame([("CARD", "baseline", 6_000_000, 3_000), ("UPI", "baseline", 1_500_000, 3_000),
                ("CARD", "current", 4_000_000, 2_000), ("UPI", "current", 1_400_000, 4_000)])
    dec = decompose(df, "seg")
    assert dec.mix_total / dec.delta >= 0.5 and dec.mix_chi2_p < 1e-9
    assert all(x.p_value is None for x in dec.segments)
    assert not dec.simpson_flag


def test_r24_adtributor_pick_stops_at_tep():
    from sherpa.drivers import _adtributor_pick
    dim = lambda name, rows: DimensionDecomposition(
        dimension=name, r0=.9, r1=.9, delta=0, mix_total=0, rate_total=0, score=0, simpson_flag=False, segments=[],
        adtributor=[{"segment": s, "ep": e, "surprise": su} for s, e, su in rows])
    a = dim("A", [("a", 0.9, 0.010)])
    b = dim("B", [("b1", 0.45, 0.005), ("b2", 0.35, 0.003), ("b3", 0.20, 0.0025)])   # summing all would give 0.0105
    assert _adtributor_pick(a) == ("a", 0.010)
    assert _adtributor_pick(b) == ("b1", pytest.approx(0.008))
    assert _adtributor_pick(dim("C", [("c1", 0.3, 0.01), ("c2", 0.05, 0.02)])) == (None, 0.0)   # never reaches TEP


def test_r18_noise_gate_looks_at_the_named_dimension_and_drill_cells():
    from sherpa.drivers import _within_noise
    flat = frame([("A", "baseline", 9_000, 10_000), ("B", "baseline", 8_000, 10_000),
                  ("A", "current", 9_001, 10_000), ("B", "current", 7_999, 10_000)])
    best = decompose(flat, "seg")                      # flat total, flat segments, no mix shift
    cell = decompose(frame([("x", "baseline", 950, 1_000), ("x", "current", 850, 1_000)]), "seg")
    assert cell.segments[0].significant
    assert _within_noise(best, [])                     # a significant segment elsewhere is not passed in
    assert not _within_noise(best, [cell])             # a sharp break in a drill cell is not noise
