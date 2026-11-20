"""End-to-end pipeline tests on the seeded DB, LLM-free: plans are given and narration uses the template."""
import json
import re
from pathlib import Path

import pytest

from sherpa import llm, narrate, pipeline
from sherpa.config import ROOT
from sherpa.contracts import AnalysisPlan, Filter, TimeWindow

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    def _raise(*a, **k):
        raise llm.LLMUnavailable("tests run without an LLM")
    monkeypatch.setattr(narrate, "narrate", _raise)


@pytest.fixture(scope="module")
def truth():
    p = ROOT / "data" / "ground_truth_42.json"
    if not p.exists():
        pytest.skip("data/ground_truth_42.json missing (run make seed)")
    return {s["id"]: s for s in json.loads(p.read_text())["scenarios"]}


def _plan(**kw) -> AnalysisPlan:
    return AnalysisPlan(question=kw.pop("question", "test"), route=kw.pop("route", "catalog"), **kw)


def _win(d: dict) -> TimeWindow:
    return TimeWindow(start=d["start"], end=d["end"])


PLACEHOLDER = re.compile(r"\{E\d+\.[A-Za-z0-9_]+\}")


def _assert_traceable(b):
    assert b.status == "answered", (b.status, b.error, b.refusal)
    assert b.evidence and all(e.sql and len(e.sql) == len(e.sql_hashes) for e in b.evidence)
    ids = {e.id for e in b.evidence}
    for c in b.claims:
        assert c.ok, c.problems
        assert set(c.evidence_ids) <= ids
        if c.kind == "fact":
            assert c.evidence_ids
        assert not PLACEHOLDER.search(c.rendered)


def test_s1_mix_shift_is_flagged(truth):
    s = truth["S1"]
    b = pipeline.answer(s["question"], "head", plan=_plan(intent="explain_change", metric="success_rate",
                        window=_win(s["window"]), baseline=_win(s["baseline"])))
    _assert_traceable(b)
    assert b.drivers.top_dimension in s["expected"]["dimension_any_of"]
    top = b.drivers.dimensions[0]
    assert abs(top.mix_total) >= abs(top.rate_total)
    assert b.drivers.simpson_flag


def test_s2_issuer_outage_is_localised(truth):
    s = truth["S2"]
    b = pipeline.answer(s["question"], "head", plan=_plan(intent="explain_change", metric="success_rate",
                        window=_win(s["window"]), baseline=_win(s["baseline"])))
    _assert_traceable(b)
    assert b.drivers.top_dimension == "issuer_bank"
    assert b.drivers.dimensions[0].segments[0].segment == s["expected"]["segment"]


def test_s3_drilldown_finds_cell(truth):
    s = truth["S3"]
    b = pipeline.answer(s["question"], "head", plan=_plan(intent="explain_change", metric="success_rate",
                        window=_win(s["window"]), baseline=_win(s["baseline"]),
                        filters=[Filter(**f) for f in s.get("filters", [])]))
    _assert_traceable(b)
    cells = [c.dims for c in b.drivers.drilldown[:3]]
    assert s["expected"]["cell"] in cells, cells


def test_s4_reconciliation_identity(truth):
    s = truth["S4"]
    b = pipeline.answer("recon", "head", plan=_plan(intent="reconcile", metric="settled_net", window=_win(s["window"])))
    _assert_traceable(b)
    assert abs(sum(c.amount_inr for c in b.recon.components) - b.recon.gap_inr) < 1.0
    for name in ("cutoff_timing", "refunds", "fees"):
        got = next(c.amount_inr for c in b.recon.components if c.name == name)
        assert abs(got - s["expected"][name]) < 1.0, (name, got, s["expected"][name])


def test_s5_missing_hours_warned(truth):
    s = truth["S5b"]
    d = s["expected"]["date"]
    b = pipeline.answer("dq", "head", plan=_plan(intent="data_quality", metric="attempts",
                        window=TimeWindow(start=d, end=d)))
    assert b.status == "answered"
    assert any(w.check == "missing_data" and s["expected"]["gateway"] in w.message for w in b.dq), b.dq


def test_out_of_scope_region_refused_with_patch():
    b = pipeline.answer("North SR", "rm_south", plan=_plan(intent="metric_value", metric="success_rate",
                        filters=[Filter(dimension="region", values=["North"])], window=TimeWindow(preset="last_7_days")))
    assert b.status == "refused" and b.refusal and "North" in b.refusal.reason
    assert not b.evidence  # nothing ran


def test_rls_backstop_by_region_breakdown():
    b = pipeline.answer("SR by region", "rm_south", plan=_plan(intent="breakdown", metric="success_rate",
                        dimensions=["region"], window=TimeWindow(preset="last_7_days")))
    _assert_traceable(b)
    regions = {row["region"] for e in b.evidence if e.kind == "breakdown" for row in e.table}
    assert regions == {"South"}


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE analytics.transactions",
    "SELECT set_config('role', 'postgres', false)",
    "SELECT * FROM raw.transaction_events",
    "SELECT count(*) FROM analytics.transactions a, analytics.transactions b",
])
def test_unsafe_sql_route_refused(sql):
    b = pipeline.answer("unsafe", "head", plan=_plan(route="sql", intent="breakdown", sql=sql,
                        window=TimeWindow(preset="last_7_days")))
    assert b.status == "refused", (b.status, b.error)


def test_denominator_ambiguity_asks_with_previews():
    from sherpa.contracts import Ambiguity
    b = pipeline.answer("What was our success rate last week?", "head", plan=_plan(
        intent="metric_value", metric="success_rate", window=TimeWindow(preset="last_7_days"),
        ambiguities=[Ambiguity(kind="denominator", description="drop-offs?",
                               options=["success_rate", "success_rate_incl_dropoffs"])]))
    assert b.status == "clarify" and len(b.clarification.options) == 2
    assert all(o.preview for o in b.clarification.options)


def test_runs_are_logged():
    from sherpa import runs
    b = pipeline.answer("SR", "head", plan=_plan(intent="metric_value", metric="success_rate",
                        window=TimeWindow(preset="yesterday")))
    assert any(r["run_id"] == b.run_id for r in runs.recent_runs(20))


def test_denominator_not_asked_when_both_readings_agree(truth):
    """S3: cards fell under both definitions (-0.67 pp / -1.10 pp): same story, so no clarification."""
    from sherpa.contracts import Ambiguity
    s = truth["S3"]
    b = pipeline.answer(s["question"], "head", plan=_plan(
        intent="explain_change", metric="success_rate", window=_win(s["window"]), baseline=_win(s["baseline"]),
        filters=[Filter(**f) for f in s.get("filters", [])],
        ambiguities=[Ambiguity(kind="denominator", description="drop-offs?",
                               options=["success_rate", "success_rate_incl_dropoffs"])]))
    assert b.status == "answered", (b.status, b.clarification)
    assert any("same story" in a for a in b.plan.assumptions)
