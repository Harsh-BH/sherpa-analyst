"""Run log: save_run never raises; saved runs come back in recent_runs and run_stats."""
import logging
import uuid

import psycopg
import pytest

from sherpa import runs
from sherpa.config import settings
from sherpa.contracts import AnswerBundle, Evidence


def _bundle(**kw) -> AnswerBundle:
    return AnswerBundle(run_id=f"test-{uuid.uuid4().hex[:12]}", question="Why did SR drop?", persona="head",
                        status="answered", route="catalog", confidence="high", data_version="v-test",
                        evidence=[Evidence(id="E1", kind="metric", title="SR", sql=["SELECT 1", "SELECT 2"]),
                                  Evidence(id="E2", kind="metric", title="SR", sql=["SELECT 1"])],
                        timings_ms={"total": 1200, "queries": 4, "cache_hits": 1},
                        llm_usage={"backend": "none", "cost_usd": 0.01}, **kw)


def test_save_run_never_raises(monkeypatch, caplog):
    def boom():
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(runs, "_connect", boom)
    with caplog.at_level(logging.ERROR):
        runs.save_run(_bundle())
    assert "save_run failed" in caplog.text


@pytest.fixture
def cleanup():
    ids: list[str] = []
    yield ids
    with psycopg.connect(settings().admin_dsn()) as conn:
        conn.execute("DELETE FROM app.runs WHERE run_id = ANY(%s)", (ids,))


@pytest.mark.db
def test_save_and_read_back(cleanup, caplog):
    b = _bundle()
    cleanup.append(b.run_id)
    runs.save_run(b)
    row = next(r for r in runs.recent_runs(500) if r["run_id"] == b.run_id)
    assert row["sql"] == ["SELECT 1", "SELECT 2"] and row["timings_ms"]["total"] == 1200
    assert row["evidence"][0]["id"] == "E1" and row["llm_usage"]["cost_usd"] == 0.01
    with caplog.at_level(logging.ERROR):
        runs.save_run(b)                              # duplicate run_id: logged, not raised
    assert "save_run failed" in caplog.text


@pytest.mark.db
def test_run_stats(cleanup):
    for status, total in [("answered", 1000), ("refused", 3000), ("clarify", 2000)]:
        b = _bundle()
        b.status, b.timings_ms = status, {"total": total, "queries": 2, "cache_hits": 1}
        cleanup.append(b.run_id)
        runs.save_run(b)
    s = runs.run_stats()
    assert set(s) == {"runs", "p50_ms", "p95_ms", "refusal_rate", "clarify_rate", "cache_hit_rate", "llm_cost_usd"}
    assert s["runs"] >= 3 and 0 < s["refusal_rate"] < 1 and 0 < s["clarify_rate"] < 1
    assert s["p50_ms"] <= s["p95_ms"] and 0 < s["cache_hit_rate"] <= 1 and s["llm_cost_usd"] >= 0.03
