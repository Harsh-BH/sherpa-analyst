"""Run log: every AnswerBundle lands in app.runs, written and read as the app role (sherpa_app),
which can INSERT/SELECT app.runs and nothing else.

Each row carries source = $SHERPA_RUN_SOURCE (default 'app'; pytest sets 'test', eval/run.py 'eval'),
and the readers return source = 'app' rows only, so the Runs page shows runs people asked in the app.

A row also keeps the whole bundle, so a run can be reopened (history, permalinks), and app.run_feedback holds
thumbs up/down. Both are read for one persona only: a run of another persona is never returned.
"""
from __future__ import annotations

import logging
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import load_access, settings
from .contracts import AnswerBundle

log = logging.getLogger(__name__)


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings().dsn(load_access().app_role), connect_timeout=5, row_factory=dict_row)


def save_run(bundle: AnswerBundle) -> None:
    """Insert the run. Never raises into the caller: a failed log write is logged, the answer still ships."""
    try:
        d = bundle.model_dump(mode="json")
        sql = list(dict.fromkeys(s for e in bundle.evidence for s in e.sql))   # unique, in order
        with _connect() as conn:   # commits on exit
            conn.execute(
                "INSERT INTO app.runs (run_id, persona, question, status, route, plan, sql, evidence, claims,"
                " confidence, data_version, timings_ms, llm_usage, error, source, bundle)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (d["run_id"], d["persona"], d["question"], d["status"], d["route"], Jsonb(d["plan"]), sql,
                 Jsonb(d["evidence"]), Jsonb(d["claims"]), d["confidence"], d["data_version"],
                 Jsonb(d["timings_ms"]), Jsonb(d["llm_usage"]), d["error"],
                 os.environ.get("SHERPA_RUN_SOURCE", "app"), Jsonb(d)))
    except Exception:
        log.exception("save_run failed for run %s", getattr(bundle, "run_id", "?"))


def recent_runs(limit: int = 50) -> list[dict]:
    """App runs, newest first; every app.runs column but the bundle (jsonb comes back as dicts/lists), plus
    `rating`: the run's latest feedback (1, -1, or None when unrated)."""
    with _connect() as conn:
        return conn.execute("""
            SELECT r.run_id, r.asked_at, r.persona, r.question, r.status, r.route, r.plan, r.sql, r.evidence,
                   r.claims, r.confidence, r.data_version, r.timings_ms, r.llm_usage, r.error, r.source,
                   (SELECT f.rating FROM app.run_feedback f WHERE f.run_id = r.run_id
                    ORDER BY f.at DESC LIMIT 1) AS rating
            FROM app.runs r WHERE r.source = 'app' ORDER BY r.asked_at DESC LIMIT %s""", (int(limit),)).fetchall()


def history(persona: str, limit: int = 20) -> list[dict]:
    """The persona's app runs that can be reopened (a bundle was saved), newest first:
    run_id, question, status, confidence, asked_at."""
    with _connect() as conn:
        return conn.execute("""
            SELECT run_id, question, status, confidence, asked_at FROM app.runs
            WHERE source = 'app' AND persona = %s AND bundle IS NOT NULL
            ORDER BY asked_at DESC LIMIT %s""", (persona, int(limit))).fetchall()


def get_run(run_id: str, persona: str) -> AnswerBundle | None:
    """The saved bundle, or None when the run is missing, has no bundle, or is another persona's."""
    with _connect() as conn:
        row = conn.execute("SELECT bundle FROM app.runs WHERE run_id = %s AND persona = %s AND bundle IS NOT NULL",
                           (run_id, persona)).fetchone()
    return AnswerBundle.model_validate(row["bundle"]) if row else None


def save_feedback(run_id: str, persona: str, rating: int) -> bool:
    """Record a thumbs up (1) or down (-1); False, and nothing written, under get_run's not-found rules."""
    with _connect() as conn:   # commits on exit
        cur = conn.execute("""
            INSERT INTO app.run_feedback (run_id, persona, rating)
            SELECT run_id, persona, %s FROM app.runs WHERE run_id = %s AND persona = %s AND bundle IS NOT NULL""",
                           (int(rating), run_id, persona))
        return cur.rowcount == 1


def run_series(limit: int = 2000) -> list[dict]:
    """App runs oldest first, the columns the Runs charts plot: run_id, asked_at, status, timings_ms, cost_usd."""
    # ponytail: the newest `limit` runs in memory, a SQL rollup if the log outgrows a demo
    with _connect() as conn:
        rows = conn.execute("""
            SELECT run_id, asked_at, status, timings_ms, (llm_usage->>'cost_usd')::float8 AS cost_usd
            FROM app.runs WHERE source = 'app' ORDER BY asked_at DESC LIMIT %s""", (int(limit),)).fetchall()
    return rows[::-1]


def run_stats() -> dict:
    """App runs: {"runs", "p50_ms", "p95_ms", "refusal_rate", "clarify_rate", "cache_hit_rate", "llm_cost_usd",
    "helpful_rate"}. Latency is timings_ms.total; cache_hit_rate is sum(timings_ms.cache_hits) / sum(timings_ms.queries)
    (None until the pipeline records them); helpful_rate is the share of rated runs whose latest rating is up;
    rates are fractions, None when there are no runs (or no rated runs)."""
    with _connect() as conn:
        s = conn.execute("""
            SELECT count(*) AS runs,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY (timings_ms->>'total')::float8) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (timings_ms->>'total')::float8) AS p95_ms,
                   avg((status = 'refused')::int)::float8 AS refusal_rate,
                   avg((status = 'clarify')::int)::float8 AS clarify_rate,
                   sum((timings_ms->>'cache_hits')::float8)
                     / NULLIF(sum((timings_ms->>'queries')::float8), 0) AS cache_hit_rate,
                   coalesce(sum((llm_usage->>'cost_usd')::float8), 0) AS llm_cost_usd,
                   (SELECT avg((l.rating = 1)::int)::float8 FROM (
                      SELECT DISTINCT ON (f.run_id) f.rating FROM app.run_feedback f
                      JOIN app.runs r ON r.run_id = f.run_id AND r.source = 'app'
                      ORDER BY f.run_id, f.at DESC) l) AS helpful_rate
            FROM app.runs WHERE source = 'app'""").fetchone()
    for k in ("p50_ms", "p95_ms"):
        s[k] = None if s[k] is None else round(s[k])
    return s
