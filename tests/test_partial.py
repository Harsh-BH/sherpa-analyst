"""Numbers before the written answer: pipeline.answer(on_partial=...) and the `partial` SSE event."""
import json

import pytest
from fastapi.testclient import TestClient

from app import api, backend
from app.api import app
from app.view import build_view
from sherpa import llm, narrate, pipeline
from sherpa.contracts import AnalysisPlan, Filter, TimeWindow

client = TestClient(app)
EXPLAIN = AnalysisPlan(question="Why did success rate change last week?", route="catalog", intent="explain_change",
                       metric="success_rate", window=TimeWindow(preset="last_7_days"))


def sse(resp) -> list[tuple[str, dict]]:
    events = []
    for block in resp.text.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def ask(question="Why did success rate drop last week?", **body):
    return client.post("/api/ask", json={"question": question, "persona": "head", **body})


@pytest.fixture
def no_llm(monkeypatch):
    def _raise(*a, **k):
        raise llm.LLMUnavailable("tests run without an LLM")
    monkeypatch.setattr(narrate, "narrate", _raise)


# ------------------------------------------------------------------ pipeline (seeded DB)
@pytest.mark.db
def test_on_partial_is_called_once_before_narrate_with_numbers_only(no_llm):
    seen: list = []
    b = pipeline.answer(EXPLAIN.question, "head", plan=EXPLAIN, on_stage=seen.append, on_partial=seen.append)
    assert b.status == "answered", (b.status, b.error)
    partials = [i for i, x in enumerate(seen) if not isinstance(x, str)]
    assert len(partials) == 1
    i = partials[0]
    assert seen[i - 1] == "dq" and seen[i + 1] == "narrate", seen   # after analysis and dq, before narrate
    p = seen[i]
    assert p.evidence and p.drivers and p.plan and p.route == "catalog" and p.run_id == b.run_id
    assert [e.id for e in p.evidence] == [e.id for e in b.evidence]
    assert p.headline is None and p.claims == [] and p.confidence is None
    assert b.headline and b.claims   # the final bundle went on; the partial is a copy, not the live object
    assert p.evidence[0] is not b.evidence[0]


@pytest.mark.db
def test_a_raising_on_partial_never_breaks_the_run(no_llm):
    def boom(_):
        raise RuntimeError("ui went away")
    b = pipeline.answer(EXPLAIN.question, "head", plan=EXPLAIN, on_partial=boom)
    assert b.status == "answered" and b.headline, (b.status, b.error)


@pytest.mark.db
def test_no_partial_when_the_run_stops_before_analysis(no_llm):
    seen: list = []
    plan = AnalysisPlan(question="North SR", route="catalog", intent="metric_value", metric="success_rate",
                        filters=[Filter(dimension="region", values=["North"])], window=TimeWindow(preset="last_7_days"))
    b = pipeline.answer("North SR", "rm_south", plan=plan, on_partial=seen.append)
    assert b.status == "refused" and seen == []


# ------------------------------------------------------------------ view
def test_build_view_of_a_partial_bundle():
    b = backend.load_fixture("explain_change").model_copy(update={"headline": None, "claims": [], "confidence": None})
    v = build_view(b, partial=True)
    assert v.partial is True and v.claims == [] and v.evidence and v.key_charts
    assert build_view(backend.load_fixture("explain_change")).partial is False


# ------------------------------------------------------------------ API stream
def test_fixture_mode_sends_a_partial_without_the_narrative_first(monkeypatch):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")
    events = sse(ask())
    assert [n for n, _ in events] == ["partial", "result"]
    p, r = events[0][1], events[1][1]
    assert p["view"]["partial"] is True and r["view"]["partial"] is False
    assert p["bundle"]["headline"] is None and p["bundle"]["claims"] == [] and p["view"]["claims"] == []
    uncited = [{**e, "cited_by": []} for e in r["view"]["evidence"]]   # nothing cites evidence before the claims exist
    assert p["view"]["evidence"] == uncited and p["view"]["key_charts"] == r["view"]["key_charts"]
    assert p["bundle"]["dq"] == r["bundle"]["dq"] and p["bundle"]["run_id"] == r["bundle"]["run_id"]
    assert r["bundle"]["headline"] and r["view"]["claims"]


@pytest.mark.parametrize("fixture", ["clarify", "refused", "error"])
def test_fixture_mode_sends_no_partial_for_runs_that_never_analysed(monkeypatch, fixture):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")
    assert [n for n, _ in sse(ask(fixture=fixture))] == ["result"]


def _fake(partial_after: str):
    stages = ["plan", "triage", "analysis", "dq", "narrate", "check"]

    class Fake:
        @staticmethod
        def answer(q, p, plan=None, on_stage=None, on_partial=None):
            b = backend.load_fixture("explain_change")
            for s in stages:
                on_stage(s)
                if s == partial_after:
                    on_partial(b.model_copy(deep=True, update={"headline": None, "claims": []}))
            return b
    return Fake


def test_sse_order_is_stages_partial_stages_result(monkeypatch):
    monkeypatch.delenv("SHERPA_UI_FIXTURES", raising=False)
    monkeypatch.setattr(backend, "pipeline_status", lambda: (_fake("dq"), None))
    events = sse(ask())
    assert [(n, d.get("name")) for n, d in events] == [
        ("stage", "plan"), ("stage", "triage"), ("stage", "analysis"), ("stage", "dq"), ("partial", None),
        ("stage", "narrate"), ("stage", "check"), ("result", None)]
    assert events[4][1]["view"]["partial"] is True and events[-1][1]["view"]["partial"] is False


def test_a_partial_that_cannot_be_viewed_is_skipped(monkeypatch):
    monkeypatch.delenv("SHERPA_UI_FIXTURES", raising=False)
    monkeypatch.setattr(backend, "pipeline_status", lambda: (_fake("dq"), None))
    real = api.build_view

    def flaky(b, *, partial=False):
        if partial:
            raise ValueError("bad partial")
        return real(b)
    monkeypatch.setattr(api, "build_view", flaky)
    names = [n for n, _ in sse(ask())]
    assert "partial" not in names and names[-1] == "result"
