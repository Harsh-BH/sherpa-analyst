"""Home: explain a dip (the trend's clickable days and unusual-day flags) and the rail's data health."""
from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import backend, overview
from app.api import app
from sherpa import db
from sherpa.compiler import compile_dq_queries, default_baseline, resolve_window
from sherpa.contracts import Filter, TimeWindow

AS_OF, START = date(2026, 11, 19), date(2026, 9, 21)
W = resolve_window(TimeWindow(preset="last_30_days"), AS_OF, START)        # 21 Oct - 19 Nov
B = resolve_window(default_baseline(W), AS_OF, START)                       # 21 Sep - 20 Oct
DAYS = [W.start + timedelta(days=i) for i in range(30)]


def _current(spec: dict) -> dict[str, dict]:
    return {r["date"][:10]: r for r in spec["data"]["values"] if r["series"] == "Last 30 days"}


def _n(daily, prev_daily=()):
    return {"value": 0.92, "prev": 0.92, "daily": list(daily), "prev_daily": list(prev_daily)}


def test_every_day_asks_why_it_moved_vs_the_day_before():
    n = _n([(DAYS[0], 0.92), (DAYS[1], 0.91), (DAYS[2], 0.93)], [(B.end, 0.925)])
    rows = _current(overview._trend(W, B, n).spec)
    # the first day compares with the last day of the previous period, which is the day before the window
    assert rows["2026-10-21"]["_ask"] == "Why did success rate fall on 21 Oct compared with the day before?"
    assert rows["2026-10-22"]["_ask"] == "Why did success rate fall on 22 Oct compared with the day before?"
    assert rows["2026-10-23"]["_ask"] == "Why did success rate rise on 23 Oct compared with the day before?"
    assert rows["2026-10-23"]["_change"] == "+2.00 pp" and rows["2026-10-23"]["_hint"] == "Click to ask Sherpa why"
    assert all("_ask" not in r for r in overview._trend(W, B, n).spec["data"]["values"] if r["series"] != "Last 30 days")


def test_first_day_without_a_known_day_before_gets_no_ask():
    rows = _current(overview._trend(W, B, _n([(DAYS[0], 0.92), (DAYS[1], 0.91)])).spec)
    assert "_ask" not in rows["2026-10-21"] and rows["2026-10-21"]["_change"] == "n/a"
    assert rows["2026-10-22"]["_ask"].startswith("Why did success rate fall on 22 Oct")


def test_points_are_clickable_and_the_line_never_asks():
    spec = overview._trend(W, B, _n([(d, 0.92) for d in DAYS], [(B.end, 0.92)])).spec
    line, points = spec["layer"]
    assert line["mark"]["type"] == "line"
    # Vega picks a line's first point for a click anywhere on it: the line layer must carry no question
    assert {"calculate": "null", "as": "_ask"} in line["transform"]
    assert points["mark"]["cursor"] == "pointer" and points["name"] == "ask_points"
    assert {"filter": {"field": "series", "equal": "Last 30 days"}} in points["transform"]


def test_unusual_days_are_two_standard_deviations_from_the_30_day_mean():
    vals = [0.92 + (0.001 if i % 2 else -0.001) for i in range(30)]
    vals[25] = 0.88                                                   # a planted dip: z far below -2
    n = _n(zip(DAYS, vals), [(B.end, 0.92)])
    rows = _current(overview._trend(W, B, n).spec)
    flagged = [d for d, r in rows.items() if r["_unusual"]]
    assert flagged == ["2026-11-15"]
    assert "Unusual days" in overview._trend(W, B, n).summary and "15 Nov 88.0%" in overview._trend(W, B, n).summary
    asks = overview._unusual(n)
    assert [(a.label, a.question) for a in asks] == [
        ("15 Nov · 88.0%", "Why did success rate fall on 15 Nov compared with the day before?")]
    flat = _n([(d, 0.92) for d in DAYS])                              # no spread: nothing is unusual
    assert not any(r["_unusual"] for r in _current(overview._trend(W, B, flat).spec).values())


# ------------------------------------------------------------------ data health
def _dq_frames(dups: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.DataFrame([{"txn_date": date(2026, 11, 18), "region": "South", "gateway": "PG_B", "raw_events": 5000,
                           "duplicate_events": dups, "null_issuer_nonwallet": 0}])
    return daily, pd.DataFrame(columns=["txn_date", "txn_hour", "gateway", "attempts"])


def test_data_health_rows_and_the_cache_key_includes_persona(monkeypatch):
    calls = []
    frames = {"head": _dq_frames(900), "rm_south": _dq_frames(400)}

    class Res:
        def __init__(self, df):
            self.df = df

    def run_query(sql, persona, **_):
        calls.append(persona)
        daily, hourly = frames[persona]
        return Res(daily if "dq_daily" in sql else hourly)

    monkeypatch.setattr(db, "data_version", lambda p: {"version": "v1", "as_of": AS_OF, "data_start": START})
    monkeypatch.setattr(db, "run_query", run_query)
    overview._health.cache_clear()
    head, south = overview.data_health("head"), overview.data_health("rm_south")
    assert head.persona == "head" and south.persona == "rm_south"
    (h,), (s,) = head.issues, south.issues
    assert "900 duplicate events" in h.text and "400 duplicate events" in s.text
    assert (h.severity, h.check, h.when) == ("warn", "duplicates", "18 Nov")
    assert h.question == "Is the transaction data for 18 Nov complete?"
    assert overview.data_health("head") is head and calls == ["head", "head", "rm_south", "rm_south"]
    overview._health.cache_clear()


def test_api_data_health_fixture_mode(monkeypatch):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")
    client = TestClient(app)
    h = client.get("/api/data-health?persona=head").json()
    assert h["available"] is True and h["persona"] == "head" and h["issues"]
    for i in h["issues"]:
        assert i["severity"] in ("info", "warn", "error") and i["when"] and i["text"]
        assert i["question"] == f"Is the transaction data for {i['when']} complete?"
    assert client.get("/api/data-health?persona=rm_south").json() == {"available": False,
                                                                       "reason": "fixture captured for head only"}
    assert client.get("/api/data-health?persona=nobody").status_code == 422
    # not an answer bundle: /api/ask never serves it as one
    assert client.post("/api/ask", json={"question": "q", "persona": "head", "fixture": "data_health"}).status_code == 422


def test_api_data_health_unavailable_on_failure(monkeypatch):
    monkeypatch.setattr(backend, "pipeline_status", lambda: (object(), None))

    def boom(persona):
        raise RuntimeError("no db\nsecond line")
    monkeypatch.setattr(overview, "data_health", boom)
    assert TestClient(app).get("/api/data-health").json() == {"available": False, "reason": "RuntimeError: no db"}


def test_eval_proof_line(monkeypatch):
    monkeypatch.setattr(backend, "EVAL_RESULTS", backend.FIXTURES / "eval_latest.json")
    assert TestClient(app).get("/api/eval").json()["proof"] == "Eval: 3/3 cases vs 1/3 for a naive baseline"


@pytest.mark.db
def test_data_health_is_persona_scoped():
    """rm_south's issues are exactly head's issues over South's rows only: RLS scopes the governed dq queries."""
    overview._health.cache_clear()
    south = overview.data_health("rm_south")
    v = db.data_version("head")
    w = resolve_window(TimeWindow(preset="last_30_days"), v["as_of"], v["data_start"])
    qs = compile_dq_queries(w, [Filter(dimension="region", values=["South"])])
    from sherpa import dq
    want = dq.run_checks(db.run_query(qs["dq_daily"], "head").df, db.run_query(qs["hourly"], "head").df,
                         window=w, as_of=v["as_of"])
    assert [i.text for i in south.issues] == [x.message for x in want]
    assert [i.text for i in overview.data_health("head").issues] != [i.text for i in south.issues]
