"""The FastAPI service in fixture mode: shapes, the SSE stream, validation, Explore, Eval and Runs."""
import json

import pytest
from fastapi.testclient import TestClient

from app import backend
from app.api import app
from app.view import fmt_ms

client = TestClient(app)


@pytest.fixture(autouse=True)
def fixture_mode(monkeypatch):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")


def sse(resp) -> list[tuple[str, dict]]:
    events = []
    for block in resp.text.strip().split("\n\n"):
        if block.startswith(":"):   # SSE comment (keep-alive)
            continue
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def ask(**body):
    return client.post("/api/ask", json={"question": "Why did success rate drop last week?", "persona": "head", **body})


def fake_pipeline(stages=()):
    class Fake:
        @staticmethod
        def answer(q, p, plan=None, on_stage=None):
            for s in stages:
                on_stage(s)
            return backend.load_fixture("explain_change")
    return Fake


def test_health_reports_fixture_mode():
    assert client.get("/api/health").json() == {"ok": True, "fixture_mode": True, "fixture_reason": "SHERPA_UI_FIXTURES=1"}


def test_meta_shape():
    m = client.get("/api/meta").json()
    assert len(m["personas"]) == 2 and m["default_persona"] == "head"
    assert m["demo"][-1] == {"question": "Compare North vs South success rate", "persona": "rm_south"}
    assert m["verified"] and "success_rate" in [x["name"] for x in m["catalog"]["metrics"]]
    assert m["catalog"]["grains"] == ["day", "hour"] and m["fixture_mode"] is True


def test_ask_streams_result_in_fixture_mode():
    events = sse(ask())
    assert [n for n, _ in events] == ["result"]
    d = events[0][1]
    assert d["bundle"]["status"] == "answered" and d["view"]["claims"]


def test_ask_streams_stages_from_pipeline(monkeypatch):
    stages = ["plan", "triage", "analysis", "dq", "narrate", "check"]
    monkeypatch.setattr(backend, "pipeline_status", lambda: (fake_pipeline(stages), None))
    events = sse(ask())
    assert [n for n, _ in events] == ["stage"] * 6 + ["result"]
    assert [d["name"] for n, d in events[:6]] == stages
    t = [d["t_ms"] for n, d in events[:6]]
    assert t == sorted(t)
    assert [d["elapsed"] for n, d in events[:6]] == [fmt_ms(ms) for ms in t]  # the trace shows it as-is


def test_ask_sets_streaming_headers():
    r = ask()
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache, no-transform" and r.headers["x-accel-buffering"] == "no"


def test_openapi_documents_the_ask_result():
    """web/lib/api-types.ts is generated from /openapi.json, so the `result` event's payload must be in it."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"AskResult", "AnswerBundle", "View"} <= set(schemas)


def test_ask_rejects_bad_input():
    assert ask(persona="nobody").status_code == 422
    assert ask(question="x" * 501).status_code == 422
    assert ask(question="   ").status_code == 422
    assert ask(fixture="../../etc/passwd").status_code == 422
    assert ask(patch={"metric": "success_rate"}).status_code == 422


def test_ask_fixture_param_only_in_fixture_mode(monkeypatch):
    monkeypatch.delenv("SHERPA_UI_FIXTURES")
    monkeypatch.setattr(backend, "pipeline_status", lambda: (fake_pipeline(), None))
    assert sse(ask(fixture="error"))[0][1]["bundle"]["status"] == "answered"
    assert sse(ask(fixture="error"))[0][1]["bundle"]["run_id"] == "fx-explain-0001"


def test_ask_patch_applies():
    c = backend.load_fixture("clarify")
    r = ask(question=c.question, plan=c.plan.model_dump(mode="json"), patch=c.clarification.options[0].plan_patch)
    assert sse(r)[0][1]["bundle"]["status"] != "clarify"


def test_ask_unexpected_error_keeps_a_run_id(monkeypatch):
    monkeypatch.setattr(backend, "answer", lambda *a, **k: 1 / 0)
    b = sse(ask())[0][1]["bundle"]
    assert b["status"] == "error" and b["run_id"].startswith("ui-") and "ZeroDivisionError" in b["error"]


def test_ask_keeps_a_slow_stage_alive(monkeypatch):
    """A stage longer than a proxy's idle timeout (Next.js: 30 s) must not leave the stream silent."""
    import time

    from app import api
    monkeypatch.setattr(api, "KEEPALIVE_S", 0.05)

    def slow(q, p, plan=None, on_stage=None):
        time.sleep(0.3)
        return backend.load_fixture("explain_change")
    monkeypatch.setattr(backend, "answer", slow)
    r = ask()
    assert r.text.startswith(": keepalive\n\n")
    assert [n for n, _ in sse(r)] == ["result"]


def test_explore_plan_builds_question_and_plan():
    form = {"intent": "breakdown", "metric": "success_rate", "dimensions": ["payment_method"], "window": "last_7_days",
            "filters": [{"dimension": "region", "values": ["South"]}]}
    r = client.post("/api/explore/plan", json=form).json()
    assert r["question"] == "Breakdown: Success rate by Payment method last 7 days where Region in South"
    assert r["plan"]["route"] == "catalog"
    assert client.post("/api/explore/plan", json={**form, "metric": "nope"}).status_code == 422
    assert client.post("/api/explore/plan", json={**form, "dimensions": ["nope"]}).status_code == 422
    assert client.post("/api/explore/plan", json={**form, "window": "nope"}).status_code == 422


def test_eval_and_runs_fallbacks(monkeypatch):
    e = client.get("/api/eval").json()
    assert e["status"] == "ok" and len(e["tiles"]) == 7 and e["cases"]
    assert e["tiles"][0] == {"label": "Result equivalence", "sherpa": "95%", "baseline": "60%"} or e["fixture"] is False
    import sherpa.runs

    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(sherpa.runs, "run_stats", boom)
    r = client.get("/api/runs").json()
    assert r["status"] == "unavailable" and "no db" in r["message"]


def test_eval_missing_and_error(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "EVAL_RESULTS", tmp_path / "latest.json")
    monkeypatch.setattr(backend, "pipeline_status", lambda: (object(), None))
    assert client.get("/api/eval").json()["status"] == "missing"
    (tmp_path / "latest.json").write_text("{not json")
    assert client.get("/api/eval").json()["status"] == "error"


def test_runs_ok(monkeypatch):
    import sherpa.runs
    monkeypatch.setattr(sherpa.runs, "run_stats", lambda: {"runs": 3, "p50_ms": 4200, "p95_ms": 9000, "llm_cost_usd": 0.5,
                                                           "refusal_rate": 0.1, "clarify_rate": 0.0, "cache_hit_rate": None})
    monkeypatch.setattr(sherpa.runs, "recent_runs", lambda n: [{
        "run_id": "r1", "asked_at": __import__("datetime").datetime(2026, 11, 20, 10, 0), "persona": "head", "question": "q",
        "status": "answered", "route": None, "confidence": "high", "timings_ms": {"total": 4200, "plan": 90},
        "llm_usage": {"backend": "claude-cli", "cost_usd": 0.1234}}])
    r = client.get("/api/runs").json()
    assert r["status"] == "ok" and len(r["tiles"]) == 7 and r["tiles"][0] == {"label": "Runs", "value": "3"}
    assert r["tiles"][6]["value"] == "n/a"
    row = r["recent"][0]
    assert row["total"] == "4.2 s" and row["cost"] == "$0.12" and row["route"] == "n/a"
    assert {"label": "plan", "value": "90 ms"} in row["footprint"]


def test_partial_fixture_view():
    b = sse(ask(fixture="partial"))[0][1]

    def no_float(x):   # chart specs ("chart", "spec") are plot data for vega, a fraction is a bar width: not text
        if isinstance(x, dict):
            return all(no_float(v) for k, v in x.items() if k not in ("chart", "spec", "fraction"))
        if isinstance(x, list):
            return all(no_float(v) for v in x)
        return not isinstance(x, float)
    assert b["view"]["claims"][0]["missing_ids"] == ["E9"]
    assert no_float(b["view"])
