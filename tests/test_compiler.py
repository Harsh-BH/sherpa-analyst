"""Compiler: windows, catalog verified queries -> guarded SQL, typed literals. No database needed."""
from datetime import date

import pytest
import sqlglot
from sqlglot import exp

from sherpa.compiler import (compile_dq_queries, compile_metric, compile_recon_queries, default_baseline,
                             metric_value, resolve_window)
from sherpa.config import load_catalog
from sherpa.contracts import AnalysisPlan, Filter, TimeWindow
from sherpa.guard import check_sql

AS_OF, START = date(2026, 11, 19), date(2026, 9, 21)   # as_of is a Thursday
D = date


def rw(preset, as_of=AS_OF, start=START):
    w = resolve_window(TimeWindow(preset=preset), as_of, start)
    return w.start, w.end


@pytest.mark.parametrize("preset,expected", [
    ("yesterday", (D(2026, 11, 19), D(2026, 11, 19))),
    ("last_7_days", (D(2026, 11, 13), D(2026, 11, 19))),
    ("previous_7_days", (D(2026, 11, 6), D(2026, 11, 12))),
    ("last_14_days", (D(2026, 11, 6), D(2026, 11, 19))),
    ("last_28_days", (D(2026, 10, 23), D(2026, 11, 19))),
    ("last_30_days", (D(2026, 10, 21), D(2026, 11, 19))),
    ("month_to_date", (D(2026, 11, 1), D(2026, 11, 19))),
    ("last_month", (D(2026, 10, 1), D(2026, 10, 31))),
    ("last_calendar_week", (D(2026, 11, 9), D(2026, 11, 15))),   # Mon..Sun before Thursday as_of
    ("all_data", (START, AS_OF)),
])
def test_presets(preset, expected):
    assert rw(preset) == expected


def test_week_and_month_boundaries():
    long_ago = D(2025, 1, 1)
    # as_of on a Sunday that is also the 1st: that week is complete, MTD is one day
    assert rw("last_calendar_week", D(2026, 11, 1), long_ago) == (D(2026, 10, 26), D(2026, 11, 1))
    assert rw("month_to_date", D(2026, 11, 1), long_ago) == (D(2026, 11, 1), D(2026, 11, 1))
    # as_of on a Monday: last complete week ended yesterday
    assert rw("last_calendar_week", D(2026, 11, 16), long_ago) == (D(2026, 11, 9), D(2026, 11, 15))
    # last_month across a year boundary and in February
    assert rw("last_month", D(2026, 1, 5), long_ago) == (D(2025, 12, 1), D(2025, 12, 31))
    assert rw("last_month", D(2026, 3, 1), long_ago) == (D(2026, 2, 1), D(2026, 2, 28))
    # last_7_days spanning a month boundary
    assert rw("last_7_days", D(2026, 11, 3), long_ago) == (D(2026, 10, 28), D(2026, 11, 3))


def test_labels_and_clamping():
    assert resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START).label == "last 7 days (13-19 Nov 2026)"
    assert resolve_window(TimeWindow(preset="last_28_days"), AS_OF, START).label == "last 28 days (23 Oct - 19 Nov 2026)"
    assert resolve_window(TimeWindow(preset="yesterday"), AS_OF, START).label == "yesterday (19 Nov 2026)"
    clamped = resolve_window(TimeWindow(preset="last_month"), AS_OF, D(2026, 10, 15))
    assert (clamped.start, clamped.end) == (D(2026, 10, 15), D(2026, 10, 31))
    custom = resolve_window(TimeWindow(start=D(2026, 9, 1), end=D(2026, 12, 31)), AS_OF, START)
    assert (custom.start, custom.end, custom.label) == (START, AS_OF, "21 Sep - 19 Nov 2026")
    with pytest.raises(ValueError, match="outside the data range"):
        resolve_window(TimeWindow(preset="last_month"), AS_OF, D(2026, 11, 2))
    with pytest.raises(ValueError):
        resolve_window(TimeWindow(), AS_OF, START)
    with pytest.raises(ValueError, match="before it starts"):
        resolve_window(TimeWindow(start=D(2026, 11, 10), end=D(2026, 11, 1)), AS_OF, START)


def test_default_baseline():
    b = default_baseline(resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START))
    assert (b.start, b.end, b.label) == (D(2026, 11, 6), D(2026, 11, 12), "previous 7 days (6-12 Nov 2026)")
    b = default_baseline(resolve_window(TimeWindow(preset="month_to_date"), AS_OF, START))
    assert (b.start, b.end) == (D(2026, 10, 13), D(2026, 10, 31))
    with pytest.raises(ValueError):
        default_baseline(TimeWindow(preset="last_7_days"))


def queries_for(plan: AnalysisPlan, as_of: date = AS_OF, start: date = START) -> list[str]:
    """How the pipeline turns a catalog plan into SQL (per intent). Also used by test_db."""
    window = resolve_window(plan.window, as_of, start)
    baseline = None
    if plan.intent in ("compare_periods", "explain_change"):
        baseline = resolve_window(plan.baseline, as_of, start) if plan.baseline else default_baseline(window)
    if plan.intent == "reconcile":
        return list(compile_recon_queries(window, plan.filters).values())
    if plan.intent == "data_quality":
        return list(compile_dq_queries(window, plan.filters).values())
    if plan.intent == "explain_change":
        dims = plan.dimensions or [d.name for d in load_catalog().dimensions if d.driver]
        return [compile_metric(plan.metric, window=window, dimensions=[d], filters=plan.filters, baseline=baseline)
                for d in dims]
    grain = plan.grain if plan.intent == "trend" else None
    return [compile_metric(plan.metric, window=window, dimensions=plan.dimensions, filters=plan.filters,
                           baseline=baseline, grain=grain)]


@pytest.mark.parametrize("vq", load_catalog().verified_queries, ids=lambda v: v.name)
def test_verified_queries_compile_and_pass_guard(vq):
    plan = AnalysisPlan.model_validate({"question": vq.question, **vq.plan})
    queries = queries_for(plan)
    assert queries
    for q in queries:
        g = check_sql(q)
        assert g.tables and set(g.tables) <= {"transactions", "settlements", "dq_daily"}


def test_every_metric_and_dimension_compiles():
    cat = load_catalog()
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    for m in cat.metrics:
        dims = [d.name for d in cat.dimensions if cat.metric(m.name).table in d.tables]
        for d in dims:
            check_sql(compile_metric(m.name, window=w, dimensions=[d], baseline=default_baseline(w)))


def _aliases(sql: str) -> list[str]:
    return [e.alias_or_name for e in sqlglot.parse_one(sql, dialect="postgres").expressions]


def test_output_columns_in_contract_order():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    sql = compile_metric("success_rate", window=w, dimensions=["issuer_bank", "card_network"],
                         baseline=default_baseline(w), grain="hour")
    assert _aliases(sql) == ["issuer_bank", "card_network", "period", "bucket_date", "bucket_hour", "num", "den"]
    assert _aliases(compile_metric("gmv", window=w)) == ["num", "den"]
    assert _aliases(compile_metric("attempts", window=w, grain="day")) == ["bucket_date", "num", "den"]
    recon = compile_recon_queries(w)
    assert _aliases(recon["by_txn_date"]) == ["txn_date", "gmv_inr"]
    assert _aliases(recon["by_cycle_date"]) == ["cycle_date", "gmv_inr"]
    assert _aliases(recon["settlements"]) == ["cycle_date", "gross_inr", "refund_inr", "fee_inr", "net_inr"]
    dq = compile_dq_queries(w)
    assert _aliases(dq["hourly"]) == ["txn_date", "txn_hour", "gateway", "attempts"]
    assert "2026-11-06" in dq["hourly"]   # hourly reaches 7 days before the window


def test_settlement_metrics_use_cycle_date():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    assert "cycle_date BETWEEN" in compile_metric("gmv_settlement_basis", window=w)
    assert "cycle_date BETWEEN" in compile_metric("settled_net", window=w)
    with pytest.raises(ValueError):   # no hour column on settlements
        compile_metric("settled_net", window=w, grain="hour")
    with pytest.raises(ValueError):   # settlements are not per payment method
        compile_recon_queries(w, [Filter(dimension="payment_method", values=["UPI"])])


INJECTION = "UPI' OR 1=1 --"


def test_injection_in_closed_vocabulary_is_rejected():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    with pytest.raises(ValueError, match="not a valid Payment method"):
        compile_metric("success_rate", window=w, filters=[Filter(dimension="payment_method", values=[INJECTION])])
    with pytest.raises(ValueError):
        compile_metric("success_rate", window=w, filters=[Filter(dimension="txn_hour", values=["1 OR 1=1"])])
    with pytest.raises(ValueError):
        compile_metric("success_rate", window=w, filters=[Filter(dimension="txn_date", values=["2026-11-01' OR '1'='1"])])
    with pytest.raises(ValueError):
        compile_metric("success_rate", window=w, dimensions=["issuer_bank_id; DROP TABLE x"])


def test_injection_in_open_vocabulary_is_one_quoted_literal():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    sql = check_sql(compile_metric("success_rate", window=w,
                                   filters=[Filter(dimension="merchant", values=[INJECTION])])).sql
    tree = sqlglot.parse_one(sql, dialect="postgres")
    in_node = tree.find(exp.In)
    assert in_node.this.name == "merchant_id"
    assert [e.this for e in in_node.expressions] == [INJECTION]   # the whole string is one value
    assert not any(isinstance(e, exp.EQ) and e.left.sql() == "1" for e in tree.find_all(exp.EQ))


def test_typed_literals():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    sql = compile_metric("success_rate", window=w, filters=[Filter(dimension="txn_hour", values=["10", "11"]),
                                                            Filter(dimension="txn_date", values=["2026-11-15"])])
    assert "txn_hour IN (10, 11)" in sql and "txn_date IN (CAST('2026-11-15' AS DATE))" in sql


def test_not_in_keeps_nulls():
    w = resolve_window(TimeWindow(preset="last_7_days"), AS_OF, START)
    sql = compile_metric("success_rate", window=w, filters=[Filter(dimension="card_network", op="not_in", values=["VISA"])])
    assert "(card_network IS NULL OR NOT card_network IN ('VISA'))" in sql


def test_metric_value():
    assert metric_value("success_rate", 917, 1000) == pytest.approx(0.917)
    assert metric_value("success_rate", 0, 0) is None
    assert metric_value("gmv", 12345.5, 10) == 12345.5
