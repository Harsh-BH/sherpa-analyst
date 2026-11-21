from app import backend
from app.view import View, build_view, fmt_ms

FIXTURES = ("explain_change", "clarify", "refused", "sql_route", "reconcile", "error")
INJECTION_KEY = "display_name"


def test_claims_carry_rendered_text_and_dedup_ids():
    b = backend.load_fixture("explain_change")
    assert [c.text for c in build_view(b).claims] == [c.rendered for c in b.claims]
    b.claims[0].evidence_ids = ["E1", "E1", "E9"]
    c = build_view(b).claims[0]
    assert c.n == 1 and c.evidence_ids == ["E1"] and c.missing_ids == ["E9"]
    assert 1 in build_view(b).evidence[0].cited_by


def test_tables_match_streamlit_formatting():
    def col(t, name):
        return [r[t.columns.index(name)] for r in t.rows]
    e1, e2, _ = build_view(backend.load_fixture("explain_change")).evidence
    assert col(e1.table, "rate") == ["92.8%", "91.7%"]
    assert col(e2.table, "share0") == ["40.0%", "60.0%"]
    assert col(e2.table, "mix_effect") == ["-0.80 pp", "-0.80 pp"]
    assert col(build_view(backend.load_fixture("reconcile")).evidence[0].table, "amount_inr")[0] == "₹4.20 L"
    raw = backend.load_fixture("sql_route")
    t = build_view(raw).evidence[0].table
    assert col(t, "display_name")[1] == str(raw.evidence[0].table[1]["display_name"])
    assert col(t, "merchant_id")[0] == "M0042" and col(t, "failed")[0] == "812"


def _leaves(x, key=""):
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in ("spec", "chart"):
                yield from _leaves(v, k)
    elif isinstance(x, list | tuple):
        for v in x:
            yield from _leaves(v, key)
    else:
        yield key, x


def test_every_number_is_a_string():
    for name in FIXTURES:
        for key, v in _leaves(build_view(backend.load_fixture(name)).model_dump()):
            if isinstance(v, int | float) and not isinstance(v, bool):
                assert key in ("n", "cited_by"), (name, key, v)


def test_key_charts_and_simpson():
    b = backend.load_fixture("explain_change")
    v = build_view(b)
    assert len(v.key_charts) == len(b.drivers.dimensions) and v.default_dimension == b.drivers.top_dimension
    flagged = [k for k, d in zip(v.key_charts, b.drivers.dimensions) if d.simpson_flag]
    assert flagged and all("Simpson's paradox" in k.simpson for k in flagged)
    assert all(k.simpson is None for k in v.key_charts if k not in flagged)
    assert v.drivers and v.drivers.tables and v.fallback_chart is None


def test_recon_view():
    v = build_view(backend.load_fixture("reconcile"))
    assert v.recon.components.columns == ["component", "amount", "note"] and v.recon.spec


def test_footprint():
    b = backend.load_fixture("explain_change")
    b.timings_ms = {"plan": 6127, "narrate": 8182, "total": 14827, "queries": 20, "cache_hits": 20}
    b.llm_usage = {"backend": "claude-cli", "cost_usd": 0.02451}
    f = build_view(b).footprint
    assert f.summary == "2 steps · 14.8 s · $0.0245"
    assert ("Cache", "20 of 20 queries") in [(i.label, i.value) for i in f.items]
    b.llm_usage = {"backend": "claude-cli", "cost_usd": None}
    assert "$" not in build_view(b).footprint.summary


def test_fmt_ms():
    assert (fmt_ms(None), fmt_ms(20), fmt_ms(6127)) == ("n/a", "20 ms", "6.1 s")
