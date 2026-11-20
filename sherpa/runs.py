"""Run log: every AnswerBundle lands in app.runs, written and read as the app role (sherpa_app),
which can INSERT/SELECT app.runs and nothing else.
"""
from __future__ import annotations

import logging

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
                " confidence, data_version, timings_ms, llm_usage, error)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (d["run_id"], d["persona"], d["question"], d["status"], d["route"], Jsonb(d["plan"]), sql,
                 Jsonb(d["evidence"]), Jsonb(d["claims"]), d["confidence"], d["data_version"],
                 Jsonb(d["timings_ms"]), Jsonb(d["llm_usage"]), d["error"]))
    except Exception:
        log.exception("save_run failed for run %s", getattr(bundle, "run_id", "?"))


def recent_runs(limit: int = 50) -> list[dict]:
    """Newest first; every app.runs column (jsonb comes back as dicts/lists)."""
    with _connect() as conn:
        return conn.execute("SELECT * FROM app.runs ORDER BY asked_at DESC LIMIT %s", (int(limit),)).fetchall()


def run_stats() -> dict:
    """{"runs", "p50_ms", "p95_ms", "refusal_rate", "clarify_rate", "cache_hit_rate", "llm_cost_usd"}.
    Latency is timings_ms.total; cache_hit_rate is sum(timings_ms.cache_hits) / sum(timings_ms.queries)
    (None until the pipeline records them); rates are fractions, None when there are no runs."""
    with _connect() as conn:
        s = conn.execute("""
            SELECT count(*) AS runs,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY (timings_ms->>'total')::float8) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (timings_ms->>'total')::float8) AS p95_ms,
                   avg((status = 'refused')::int)::float8 AS refusal_rate,
                   avg((status = 'clarify')::int)::float8 AS clarify_rate,
                   sum((timings_ms->>'cache_hits')::float8)
                     / NULLIF(sum((timings_ms->>'queries')::float8), 0) AS cache_hit_rate,
                   coalesce(sum((llm_usage->>'cost_usd')::float8), 0) AS llm_cost_usd
            FROM app.runs""").fetchone()
    for k in ("p50_ms", "p95_ms"):
        s[k] = None if s[k] is None else round(s[k])
    return s
