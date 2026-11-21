"""The FastAPI service in fixture mode: shapes, the SSE stream, validation, Explore, Eval and Runs."""
import json

import pytest
from fastapi.testclient import TestClient

from app import api, backend
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
        def answer(q, p, plan=None, on_stage=None, on_partial=None):
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
    assert [n for n, _ in events] == ["partial", "result"]   # fixture mode sends the numbers first, as the pipeline does
    d = events[-1][1]
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
    assert sse(r)[-1][1]["bundle"]["status"] != "clarify"


def test_ask_unexpected_error_keeps_a_run_id(monkeypatch):
    monkeypatch.setattr(backend, "answer", lambda *a, **k: 1 / 0)
    b = sse(ask())[0][1]["bundle"]
    assert b["status"] == "error" and b["run_id"].startswith("ui-") and "ZeroDivisionError" in b["error"]


def test_ask_keeps_a_slow_stage_alive(monkeypatch):
    """A stage longer than a proxy's idle timeout (Next.js: 30 s) must not leave the stream silent."""
    import time

    from app import api
    monkeypatch.setattr(api, "KEEPALIVE_S", 0.05)

    def slow(q, p, plan=None, on_stage=None, on_partial=None):
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
        "llm_usage": {"backend": "claude-cli", "cost_usd": 0.1234}, "rating": -1}])
    r = client.get("/api/runs").json()
    assert r["status"] == "ok" and len(r["tiles"]) == 8 and r["tiles"][0] == {"label": "Runs", "value": "3"}
    assert r["tiles"][6]["value"] == "n/a" and r["tiles"][7] == {"label": "Helpful", "value": "n/a"}
    row = r["recent"][0]
    assert row["total"] == "4.2 s" and row["cost"] == "$0.12" and row["route"] == "n/a" and row["feedback"] == "down"
    assert {"label": "plan", "value": "90 ms"} in row["footprint"]


def test_partial_fixture_view():
    b = sse(ask(fixture="partial"))[-1][1]

    def no_float(x):   # chart specs ("chart", "spec") are plot data for vega, a fraction is a bar width: not text
        if isinstance(x, dict):
            return all(no_float(v) for k, v in x.items() if k not in ("chart", "spec", "fraction"))
        if isinstance(x, list):
            return all(no_float(v) for v in x)
        return not isinstance(x, float)
    assert b["view"]["claims"][0]["missing_ids"] == ["E9"]
    assert no_float(b["view"])


def test_overview_serves_its_fixture_in_fixture_mode():
    o = client.get("/api/overview?persona=head").json()
    assert o["available"] is True and o["as_of"] and o["window"]
    assert [k["key"] for k in o["kpis"]] == ["success_rate", "gmv", "attempts", "technical_decline_rate"]
    for k in o["kpis"]:
        assert k["value"] and k["delta"] and k["summary"] and k["direction"] in ("up", "down", "flat")
        assert k["tone"] in ("positive", "negative", "neutral") and k["spark"]["height"] == 40
        assert len(k["spark"]["data"]["values"]) == 30
    assert o["trend"]["key"] == "overview-trend" and o["trend"]["summary"] and o["trend"]["spec"]["mark"]["type"] == "line"
    assert client.get("/api/overview?persona=nobody").status_code == 422
    # the fixture is head's: another persona gets no panel rather than head's all-region numbers
    assert client.get("/api/overview?persona=rm_south").json() == {"available": False,
                                                                   "reason": "fixture captured for head only"}


def test_overview_unavailable_on_failure(monkeypatch):
    from app import overview
    monkeypatch.setattr(backend, "pipeline_status", lambda: (object(), None))

    def boom(persona):
        raise RuntimeError("no db\nsecond line")
    monkeypatch.setattr(overview, "build", boom)
    assert client.get("/api/overview").json() == {"available": False, "reason": "RuntimeError: no db"}


def test_eval_charts(monkeypatch):
    monkeypatch.setattr(backend, "EVAL_RESULTS", backend.FIXTURES / "eval_latest.json")
    charts = {c["key"]: c for c in client.get("/api/eval").json()["charts"]}
    assert list(charts) == ["eval-vs-baseline", "eval-by-kind"]
    vs = charts["eval-vs-baseline"]["spec"]["data"]["values"]
    assert {"metric": "Result equivalence", "system": "Sherpa", "rate": 0.95, "_label": "95%"} in vs
    assert {"metric": "Correct clarifications", "system": "Baseline", "rate": 0.0, "_label": "0%"} in vs
    assert len(vs) == 8 and "Result equivalence 95% vs 60%" in charts["eval-vs-baseline"]["summary"]
    kinds = {(r["kind"], r["system"]): r["_label"] for r in charts["eval-by-kind"]["spec"]["data"]["values"]}
    assert kinds[("Refusal (n=1)", "Sherpa")] == "100%" and kinds[("Refusal (n=1)", "Baseline")] == "0%"
    assert api._kind("unsafe_sql") == "Unsafe SQL" and api._kind("planted_cause") == "Planted cause"
    assert client.get("/api/eval").json()["generated_at"] == "21 Nov 2026 03:00 IST"   # formatted, not raw ISO


def _series():
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)   # 15:30 IST
    return [{"run_id": f"r{i}", "asked_at": t0 + timedelta(minutes=40 * i), "status": s, "cost_usd": c,
             "timings_ms": {"plan": 1000 * (i + 1), "narrate": 3000, "total": 5000 + 1000 * i}}
            for i, (s, c) in enumerate([("answered", 0.01), ("clarify", None), ("error", 0.02)])]


def test_runs_charts(monkeypatch):
    import sherpa.runs
    monkeypatch.setattr(sherpa.runs, "run_stats", lambda: {"runs": 3})
    monkeypatch.setattr(sherpa.runs, "recent_runs", lambda n: [])
    monkeypatch.setattr(sherpa.runs, "run_series", lambda: _series())
    charts = {c["key"]: c for c in client.get("/api/runs").json()["charts"]}
    assert list(charts) == ["runs-over-time", "stage-time", "latency", "llm-spend"]
    assert all(c["title"] and c["summary"] for c in charts.values())
    over = charts["runs-over-time"]["spec"]
    assert over["encoding"]["x"]["timeUnit"] == "yearmonthdatehours"           # span <= 2 days: hourly
    assert over["data"]["values"][0]["t"] == "2026-11-21T15:30:00"             # IST wall clock
    assert "3 runs: 1 answered, 1 clarify, 0 refused, 1 error" in charts["runs-over-time"]["summary"]
    stage = {r["stage"]: r["_label"] for r in charts["stage-time"]["spec"]["data"]["values"]}
    assert stage == {"Plan": "2.0 s", "Narration": "3.0 s"}                    # mean over runs, pipeline order
    spend = charts["llm-spend"]["spec"]["data"]["values"]
    assert [r["_label"] for r in spend] == ["$0.0100", "$0.0300"]              # cumulative, runs with a cost
    assert charts["llm-spend"]["summary"].startswith("LLM spend: $0.0300 in total")   # same text as the last point
    assert [r["_label"] for r in charts["latency"]["spec"]["data"]["values"]] == ["5.0 s", "6.0 s", "7.0 s"]


def test_runs_charts_daily_and_empty(monkeypatch):
    import sherpa.runs
    from datetime import timedelta
    s = _series()
    s[-1]["asked_at"] += timedelta(days=3)
    monkeypatch.setattr(sherpa.runs, "run_stats", lambda: {"runs": 3})
    monkeypatch.setattr(sherpa.runs, "recent_runs", lambda n: [])
    monkeypatch.setattr(sherpa.runs, "run_series", lambda: s)
    over = client.get("/api/runs").json()["charts"][0]["spec"]
    assert over["encoding"]["x"]["timeUnit"] == "yearmonthdate"
    monkeypatch.setattr(sherpa.runs, "run_series", lambda: [])
    assert client.get("/api/runs").json()["charts"] == []
