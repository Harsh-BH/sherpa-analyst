"""Executor against the seeded Postgres: region scope, DB backstop, cost gate, timeout, truncation, cache."""
from datetime import date

import pytest

from sherpa import db
from sherpa.config import load_catalog
from sherpa.contracts import AnalysisPlan, QueryRejected
from tests.test_compiler import queries_for

pytestmark = pytest.mark.db

BY_REGION = "SELECT region, count(*) AS n FROM transactions GROUP BY region ORDER BY region"


def test_data_version():
    v = db.data_version("rm_south")
    assert set(v) == {"version", "seed", "data_start", "as_of"}
    assert isinstance(v["as_of"], date) and v["data_start"] < v["as_of"]


def test_region_scope_comes_from_the_database():
    head = db.run_query(BY_REGION, "head", use_cache=False).df
    south = db.run_query(BY_REGION, "rm_south", use_cache=False).df
    assert sorted(head.region) == ["East", "North", "South", "West"]
    assert list(south.region) == ["South"]
    assert south.n[0] == head.set_index("region").n["South"]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM raw.transaction_events",
    "SELECT question FROM app.runs",
    "SELECT rolname, rolpassword FROM pg_catalog.pg_authid",
])
def test_guard_bypass_is_stopped_by_db_grants(sql):
    """Skip the guard entirely: the persona's DB role must still refuse."""
    with pytest.raises(QueryRejected) as ei:
        db._run(sql, "rm_south", use_cache=False)
    assert ei.value.stage == "access" and "permission denied" in ei.value.reason


def test_guard_bypass_cannot_write():
    with pytest.raises(QueryRejected) as ei:
        db._run("DELETE FROM analytics.banks", "head", use_cache=False)
    assert ei.value.stage in ("access", "db")


def test_heavy_query_rejected_at_cost():
    with pytest.raises(QueryRejected) as ei:
        db.run_query("SELECT count(*) FROM transactions a JOIN transactions b ON a.merchant_id = b.merchant_id", "head")
    assert ei.value.stage == "cost" and "too expensive" in ei.value.reason


def test_slow_legit_query_times_out():
    with pytest.raises(QueryRejected) as ei:
        db.run_query("SELECT merchant_id, count(*) FROM transactions GROUP BY merchant_id", "head",
                     timeout_ms=5, use_cache=False)
    assert ei.value.stage == "timeout" and "5 ms" in ei.value.reason


def test_truncation_flag():
    r = db.run_query("SELECT txn_id FROM transactions", "head", max_rows=10, use_cache=False)
    assert (r.row_count, r.truncated, len(r.df)) == (10, True, 10)
    r = db.run_query("SELECT txn_id FROM transactions LIMIT 3", "head", max_rows=10, use_cache=False)
    assert (r.row_count, r.truncated) == (3, False)


def test_cache_hit_returns_a_copy():
    sql = "SELECT payment_method, count(*) AS n FROM transactions WHERE txn_hour = 3 GROUP BY 1 ORDER BY 1"
    first = db.run_query(sql, "head")
    first.df.loc[0, "n"] = -1                      # caller mutation must not reach the cache
    second = db.run_query(sql, "head")
    assert second.cached and second.sql_hash == first.sql_hash
    assert (second.df.n > 0).all()
    assert not db.run_query(sql, "rm_south").cached   # persona is part of the key


def test_result_metadata_and_types():
    r = db.run_query("SELECT txn_date, sum(amount_paise) AS paise FROM transactions GROUP BY 1 ORDER BY 1 LIMIT 2",
                     "head", use_cache=False)
    assert len(r.sql_hash) == 12 and r.est_cost > 0 and r.tables == ["transactions"] and not r.cached
    assert isinstance(r.df.paise[0], float)          # numeric comes back as float, not Decimal


def test_unknown_persona():
    with pytest.raises(QueryRejected) as ei:
        db.run_query("SELECT 1", "intern")
    assert ei.value.stage == "access"


@pytest.mark.parametrize("vq", load_catalog().verified_queries, ids=lambda v: v.name)
def test_verified_queries_execute_as_head(vq):
    v = db.data_version("head")
    plan = AnalysisPlan.model_validate({"question": vq.question, **vq.plan})
    for sql in queries_for(plan, v["as_of"], v["data_start"]):
        r = db.run_query(sql, "head")
        assert r.row_count > 0 and not r.truncated, sql
