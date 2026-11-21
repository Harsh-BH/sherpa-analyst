"""Answer extras in the view: follow-ups, waterfall drill questions, headline chips and the Markdown copy."""
import json
from datetime import date

from app import backend
from app.answer_extras import headline_parts, tone
from app.view import build_view
from sherpa.config import load_access, load_catalog
from sherpa.contracts import DimensionDecomposition, SegmentEffect, TimeWindow
from sherpa.triage import triage

ANSWERED = ("explain_change", "sql_route", "reconcile")


def _seg(dim: str, name: str, total: float) -> SegmentEffect:
    return SegmentEffect(dimension=dim, segment=name, n0=5000, n1=5000, s0=4500, s1=4400, share0=0.25, share1=0.25,
                         rate0=0.9, rate1=0.88, mix_effect=0.0, rate_effect=total, total_effect=total,
                         supported=True, significant=True, material=True)


def _with_region(persona: str, top: str):
    """explain_change with a region decomposition whose biggest mover is `top`."""
    b = backend.load_fixture("explain_change")
    b.persona = persona
    rest = [r for r in ("North", "South", "East", "West") if r != top]
    segs = [_seg("region", top, -0.008)] + [_seg("region", r, -0.001) for r in rest]
    b.drivers.dimensions.append(DimensionDecomposition(
        dimension="region", r0=0.928, r1=0.917, delta=-0.011, mix_total=0.0, rate_total=-0.011, score=0.1,
        simpson_flag=False, segments=segs))
    return b


def _resolved(b):
    """A pipeline bundle carries resolved windows (start, end); the fixtures carry presets and labels only."""
    b.plan.window = TimeWindow(preset="last_7_days", start=date(2026, 11, 13), end=date(2026, 11, 19),
                               label="last 7 days (13-19 Nov 2026)")
    b.plan.baseline = TimeWindow(preset="previous_7_days", start=date(2026, 11, 6), end=date(2026, 11, 12),
                                 label="previous 7 days (6-12 Nov 2026)")
    return b


def _assert_valid(f, persona: str):
    """A follow-up runs: its plan passes triage as the persona (catalog names, known values, regions in scope)."""
    assert f.plan.question == f.question and f.label and len(f.question) <= 500
    assert triage(f.plan, persona).action == "proceed", (f.question, triage(f.plan, persona))
    if f.plan.intent != "data_quality":
        assert load_catalog().metric(f.plan.metric).label.lower() in f.question.lower()


# ------------------------------------------------------------------ follow-ups
def test_follow_ups_for_the_fixtures_are_valid_catalog_questions():
    v = build_view(_resolved(backend.load_fixture("explain_change")))
    assert 2 <= len(v.follow_ups) <= 4
    for f in v.follow_ups:
        _assert_valid(f, "head")
    drill = v.follow_ups[0]   # the top driver segment, by the next-best dimension
    assert drill.plan.intent == "explain_change" and drill.plan.dimensions == ["gateway"]
    assert [(x.dimension, x.values) for x in drill.plan.filters] == [("payment_method", ["UPI"])]
    assert drill.question == "Why did success rate change for payment method UPI, by gateway, in the last 7 days (13-19 Nov 2026)?"
    dq = v.follow_ups[-1]     # explain_change has a DQ warning
    assert dq.plan.intent == "data_quality" and dq.question == "Is the transaction data for the last 7 days (13-19 Nov 2026) complete?"
    trend = next(f for f in v.follow_ups if f.plan.intent == "trend")   # both weeks, day by day
    assert (trend.plan.window.start, trend.plan.window.end) == (date(2026, 11, 6), date(2026, 11, 19))
    assert trend.question == "Daily success rate, 6-19 Nov 2026"
    for name in ANSWERED:
        for f in build_view(backend.load_fixture(name)).follow_ups:
            _assert_valid(f, "head")
    assert build_view(backend.load_fixture("sql_route")).follow_ups == []   # no governed metric to follow


def test_follow_ups_only_for_answers():
    for name in ("clarify", "refused", "error"):
        assert build_view(backend.load_fixture(name)).follow_ups == []


def test_region_follow_up_is_persona_safe():
    head = build_view(_with_region("head", "North")).follow_ups
    north = [f for f in head if any(x.dimension == "region" for x in f.plan.filters)]
    assert len(north) == 1 and north[0].plan.filters[-1].values == ["North"] and "North" in north[0].question
    for f in head:
        _assert_valid(f, "head")
    south = load_access().persona("rm_south").regions
    for top in ("North", "South"):     # North is out of scope; South is all rm_south sees, so it adds nothing
        fs = build_view(_with_region("rm_south", top)).follow_ups
        assert fs
        for f in fs:
            _assert_valid(f, "rm_south")
            assert all(set(x.values) <= set(south) for x in f.plan.filters if x.dimension == "region")
            assert "North" not in f.question


def test_compare_follow_up_for_a_single_number():
    b = _resolved(backend.load_fixture("explain_change"))
    b.plan.intent, b.plan.baseline, b.drivers, b.dq = "metric_value", None, None, []
    fs = build_view(b).follow_ups
    assert [f.plan.intent for f in fs] == ["explain_change", "compare_periods"]
    assert fs[1].label == "Compare with the week before" and fs[1].plan.baseline is None
    for f in fs:
        _assert_valid(f, "head")


# ------------------------------------------------------------------ waterfall drill
def test_waterfall_segment_bars_carry_ask():
    b = backend.load_fixture("explain_change")
    v = build_view(b)
    for k, dec in zip(v.key_charts, b.drivers.dimensions):
        rows = k.spec["data"]["values"]
        label = load_catalog().dimension(dec.dimension).label.lower()
        for r in rows:
            seg = r["step"].rsplit(" · ", 1)[0]
            if r["kind"] == "Total" or seg == "Other segments":
                assert "_ask" not in r
            else:
                assert r["_ask"] == f"Why did success rate change for {label} {seg} in the last 7 days (13-19 Nov 2026)?"
                assert r["_segment"] == seg
        bar, hot = k.spec["layer"][:2]   # the drillable bars again, on top: pointer and hint on those only
        assert "cursor" not in bar["mark"] and {"field": "_hint", "title": "Drill down"} not in bar["encoding"]["tooltip"]
        assert hot["transform"] == [{"filter": "isValid(datum._ask)"}] and hot["mark"]["cursor"] == "pointer"
        assert hot["encoding"]["tooltip"] == [*bar["encoding"]["tooltip"], {"field": "_hint", "title": "Drill down"}]
    assert "_ask" not in json.dumps([e.chart for e in b.evidence])   # the pipeline's own charts stay as they were


# ------------------------------------------------------------------ headline chips
def test_headline_parts_join_back_to_the_headline():
    heads = [backend.load_fixture(n).headline for n in ANSWERED] + [
        "Success rate fell -0.80 pp on 13 Nov 2026 (last 7 days (13-19 Nov 2026)); 1,080 attempts missing, "
        "GMV +12.5% to ₹4.20 L, refunds -₹2.50 L, 812 failed in 6 hours at 02:00, 2026-11-16, M0042, E1.",
        "", "No numbers here."]
    for h in heads:
        assert "".join(p.text for p in headline_parts(h, "success_rate")) == h


def test_headline_parts_kinds():
    parts = headline_parts(backend.load_fixture("explain_change").headline, "success_rate")
    chips = [(p.text, p.kind, p.tone) for p in parts if p.kind != "text"]
    assert chips == [("-1.10 pp", "down", "negative"), ("92.8%", "value", "neutral"), ("91.7%", "value", "neutral")]
    h = "1,080 attempts on 13 Nov 2026 in the last 7 days (13-19 Nov 2026) at 02:00; ₹4.20 L, -₹2.50 L, +0.00 pp, 812."
    assert [(p.text, p.kind) for p in headline_parts(h, "gmv") if p.kind != "text"] == [
        ("1,080", "value"), ("₹4.20 L", "value"), ("-₹2.50 L", "down"), ("+0.00 pp", "value"), ("812", "value")]
    assert headline_parts("", "gmv") == []


def test_headline_polarity_follows_the_metric():
    def tones(h, metric):
        return [(p.kind, p.tone) for p in headline_parts(h, metric) if p.kind in ("up", "down")]
    assert tones("moved -0.50 pp", "technical_decline_rate") == [("down", "positive")]
    assert tones("moved +0.50 pp", "technical_decline_rate") == [("up", "negative")]
    assert tones("GMV +12.5%", "gmv") == [("up", "positive")]
    assert tones("moved +0.50 pp", None) == [("up", "neutral")]   # no metric (SQL route): direction only
    assert (tone("up", True), tone("down", True), tone("flat", True)) == ("positive", "negative", "neutral")
    v = build_view(backend.load_fixture("explain_change"))
    assert "".join(p.text for p in v.headline_parts) == backend.load_fixture("explain_change").headline


# ------------------------------------------------------------------ markdown
def test_markdown_has_every_claim_and_the_footer():
    for name in ANSWERED:
        b = backend.load_fixture(name)
        md = build_view(b).markdown
        assert md.startswith(f"## {b.headline}")
        for c in b.claims:
            assert c.rendered in md
            assert f"[{', '.join(dict.fromkeys(c.evidence_ids))}]" in md
        for w in b.dq:
            assert w.message in md
        assert f"Confidence: {b.confidence.capitalize()}" in md
        assert b.run_id in md and b.data_version in md


def test_markdown_escapes_links_and_html():
    b = backend.load_fixture("explain_change")
    b.claims[0].rendered = "See [win](javascript:alert(1)) <img src=x>"
    md = build_view(b).markdown
    assert r"See \[win\](javascript:alert(1)) \<img src=x\>" in md   # every bracket escaped: no link, no tag


# ------------------------------------------------------------------ wide tables
def test_driver_tables_name_their_key_columns():
    v = build_view(backend.load_fixture("explain_change"))
    key = ["segment", "share before", "share now", "rate before", "rate now", "total (pp)"]
    for _, t in v.drivers.tables:
        assert t.key_columns == key and set(key) < set(t.columns)
    assert v.drivers.drilldown.key_columns == key
    assert all(e.table is None or e.table.key_columns == [] for e in v.evidence)
