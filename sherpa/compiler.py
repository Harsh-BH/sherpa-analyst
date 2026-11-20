"""Compiler: governed catalog metric + plan pieces -> one Postgres SELECT, built with sqlglot builders.

Plan values (dimension names, filter values, dates) never become SQL text by string formatting: names
are looked up in the catalog, values are checked against the dimension's vocabulary and emitted as
typed literals. Only the catalog's own trusted strings (measure expr/filter) are parsed as SQL.
The output still goes through guard.check_sql before it runs.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlglot import exp

from .config import load_access, load_catalog
from .contracts import Catalog, DimensionDef, Filter, Measure, MetricDef, TimeWindow

D = "postgres"


# ============================================================== windows
def _last_complete_week(a: date) -> tuple[date, date]:
    end = a - timedelta(days=(a.weekday() + 1) % 7)   # the Sunday on or before as_of
    return end - timedelta(days=6), end


def _last_month(a: date) -> tuple[date, date]:
    end = a.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def _days(n: int, back: int = 0):
    return lambda a, s: (a - timedelta(days=back + n - 1), a - timedelta(days=back))


# Relative to as_of ("today" for the data, the last complete IST date).
_PRESETS = {
    "yesterday": _days(1),
    "last_7_days": _days(7),
    "previous_7_days": _days(7, back=7),
    "last_14_days": _days(14),
    "last_28_days": _days(28),
    "last_30_days": _days(30),
    "month_to_date": lambda a, s: (a.replace(day=1), a),
    "last_month": lambda a, s: _last_month(a),
    "last_calendar_week": lambda a, s: _last_complete_week(a),
    "all_data": lambda a, s: (s, a),
}


def _fmt_range(start: date, end: date) -> str:
    def d(x: date, year: bool = True) -> str:
        return f"{x.day} {x:%b %Y}" if year else f"{x.day} {x:%b}"
    if start == end:
        return d(end)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}-{d(end)}"
    if start.year == end.year:
        return f"{d(start, year=False)} - {d(end)}"
    return f"{d(start)} - {d(end)}"


def resolve_window(w: TimeWindow, as_of: date, data_start: date) -> TimeWindow:
    """Fills start/end/label from the preset (or checks explicit dates); clamps to [data_start, as_of]."""
    if w.preset:
        start, end = _PRESETS[w.preset](as_of, data_start)
    elif w.start and w.end:
        start, end = w.start, w.end
    else:
        raise ValueError("A time window needs a preset or both a start and an end date.")
    if end < start:
        raise ValueError(f"The window ends ({end}) before it starts ({start}).")
    start, end = max(start, data_start), min(end, as_of)
    if start > end:
        raise ValueError(f"The window is outside the data range ({_fmt_range(data_start, as_of)}).")
    rng = _fmt_range(start, end)
    return TimeWindow(preset=w.preset, start=start, end=end,
                      label=f"{w.preset.replace('_', ' ')} ({rng})" if w.preset else rng)


def default_baseline(w: TimeWindow) -> TimeWindow:
    """Equal-length window immediately before w (w must be resolved). Not clamped: resolve it to clamp."""
    if not (w.start and w.end):
        raise ValueError("Resolve the window before computing its baseline.")
    n = (w.end - w.start).days + 1
    start, end = w.start - timedelta(days=n), w.start - timedelta(days=1)
    name = "previous day" if n == 1 else f"previous {n} days"
    return TimeWindow(start=start, end=end, label=f"{name} ({_fmt_range(start, end)})")


# ============================================================== SQL pieces
def _date(d: date) -> exp.Expression:
    return exp.cast(exp.Literal.string(d.isoformat()), "date")


def _between(col: str, w: TimeWindow) -> exp.Expression:
    if not (w.start and w.end):
        raise ValueError("Windows must be resolved (resolve_window) before compiling.")
    return exp.column(col).between(_date(w.start), _date(w.end))


def _measure(m: Measure) -> exp.Expression:
    if m.agg == "sum" and not m.expr:
        raise ValueError("A sum measure needs an expression.")
    if m.agg == "count" and not m.filter:
        return exp.Count(this=exp.Star())
    val = exp.maybe_parse(m.expr, dialect=D) if m.agg == "sum" else exp.Literal.number(1)
    if m.filter:
        val = exp.Case().when(exp.condition(m.filter, dialect=D), val).else_(exp.Literal.number(0))
    return exp.func("COALESCE", exp.Sum(this=val), exp.Literal.number(0))


def _dimension(cat: Catalog, name: str, table: str) -> DimensionDef:
    try:
        d = cat.dimension(name)
    except KeyError:
        raise ValueError(f"Unknown dimension {name!r}.") from None
    if table not in d.tables:
        raise ValueError(f"Dimension {d.name} is not available for {table}.")
    return d


def _literal(d: DimensionDef, v: str) -> exp.Expression:
    v = str(v)
    if d.values is not None and v not in d.values:
        raise ValueError(f"{v!r} is not a valid {d.label} value (expected one of: {', '.join(d.values)}).")
    if d.dtype == "int":
        return exp.Literal.number(int(v))
    if d.dtype == "date":
        return _date(date.fromisoformat(v))
    return exp.Literal.string(v)


def _filter_cond(d: DimensionDef, f: Filter) -> exp.Expression:
    if not f.values:
        raise ValueError(f"The filter on {d.name} has no values.")
    cond = exp.column(d.column).isin(*(_literal(d, v) for v in f.values))
    if f.op == "not_in":   # "everything except these": rows where the column is NULL stay in
        cond = exp.paren(exp.or_(exp.column(d.column).is_(exp.null()), exp.not_(cond)))
    return cond


def _filter_conds(cat: Catalog, filters: list[Filter], table: str) -> list[exp.Expression]:
    return [_filter_cond(_dimension(cat, f.dimension, table), f) for f in filters]


def _time_col(cat: Catalog, m: MetricDef) -> str:
    return m.time_column or cat.tables[m.table].time_column


def _grouped(keys: list[tuple[exp.Expression, str]], values: list[tuple[exp.Expression, str]],
             table: str, where: list[exp.Expression]) -> str:
    q = exp.select(*(exp.alias_(e, a) for e, a in keys + values)).from_(table, dialect=D).where(exp.and_(*where))
    if keys:
        q = q.group_by(*(e.copy() for e, _ in keys)).order_by(*(e.copy() for e, _ in keys))
    return q.sql(dialect=D)


# ============================================================== metrics
def compile_metric(metric: str, *, window: TimeWindow, dimensions: list[str] = [], filters: list[Filter] = [],
                   baseline: TimeWindow | None = None, grain: str | None = None) -> str:
    """Columns: *dimensions, [period], [bucket_date], [bucket_hour], num, den (docs/CONTRACTS.md §2)."""
    cat = load_catalog()
    m = cat.metric(metric)
    tcol = _time_col(cat, m)
    keys = [(exp.column(_dimension(cat, d, m.table).column), d) for d in dimensions]
    if baseline:
        period = (exp.Case().when(_between(tcol, window), exp.Literal.string("current"))
                  .when(_between(tcol, baseline), exp.Literal.string("baseline")))
        keys.append((period, "period"))
        where = [exp.or_(_between(tcol, window), _between(tcol, baseline))]
    else:
        where = [_between(tcol, window)]
    if grain not in (None, "day", "hour"):
        raise ValueError(f"Unknown grain {grain!r}.")
    if grain:
        keys.append((exp.column(tcol), "bucket_date"))
    if grain == "hour":
        keys.append((exp.column(_dimension(cat, "txn_hour", m.table).column), "bucket_hour"))
    if m.type == "ratio":
        num, den = _measure(m.numerator), _measure(m.denominator)
    else:   # den = support: rows passing the measure's filter
        num, den = _measure(m.measure), _measure(Measure(agg="count", filter=m.measure.filter))
    return _grouped(keys, [(num, "num"), (den, "den")], cat.tables[m.table].sql_table,
                    where + _filter_conds(cat, filters, m.table))


def metric_value(metric: str, num: float, den: float) -> float | None:
    m = load_catalog().metric(metric)
    if m.type == "ratio":
        return float(num) / float(den) if den else None
    return float(num)


# ============================================================== data quality and reconciliation
def compile_dq_queries(window: TimeWindow, filters: list[Filter] = []) -> dict[str, str]:
    """dq_daily rows for the window; hourly attempts by gateway for [window.start - 7 days, window.end].
    Filters on columns dq_daily lacks (e.g. payment_method) apply to the hourly query only."""
    cat = load_catalog()
    dq_cols = load_access().exposed_tables["dq_daily"]
    dims = [(_dimension(cat, f.dimension, "transactions"), f) for f in filters]
    dq = (exp.select(*dq_cols).from_("analytics.dq_daily", dialect=D)
          .where(exp.and_(_between("txn_date", window), *(_filter_cond(d, f) for d, f in dims if d.column in dq_cols)))
          .order_by("txn_date", "region", "gateway", dialect=D).sql(dialect=D))
    wide = TimeWindow(start=window.start - timedelta(days=7), end=window.end)
    keys = [(exp.column(c), c) for c in ("txn_date", "txn_hour", "gateway")]
    hourly = _grouped(keys, [(exp.Count(this=exp.Star()), "attempts")], cat.tables["transactions"].sql_table,
                      [_between("txn_date", wide)] + [_filter_cond(d, f) for d, f in dims])
    return {"dq_daily": dq, "hourly": hourly}


def _daily(cat: Catalog, metric: str, out_col: str, values: dict[str, str], window: TimeWindow,
           filters: list[Filter]) -> str:
    """One row per day of the metric's time column: out_col, then alias -> metric measure."""
    m = cat.metric(metric)
    tcol = _time_col(cat, m)
    vals = [(_measure(cat.metric(name).measure), alias) for alias, name in values.items()]
    return _grouped([(exp.column(tcol), out_col)], vals, cat.tables[m.table].sql_table,
                    [_between(tcol, window)] + _filter_conds(cat, filters, m.table))


def compile_recon_queries(window: TimeWindow, filters: list[Filter] = []) -> dict[str, str]:
    """Transactions by calendar date and by settlement cycle vs settlement payouts, from catalog measures.
    A filter the settlements table cannot honour (e.g. payment_method) raises ValueError."""
    cat = load_catalog()
    return {
        "by_txn_date": _daily(cat, "gmv", "txn_date", {"gmv_inr": "gmv"}, window, filters),
        "by_cycle_date": _daily(cat, "gmv_settlement_basis", "cycle_date", {"gmv_inr": "gmv_settlement_basis"},
                                window, filters),
        "settlements": _daily(cat, "settled_gross", "cycle_date",
                              {"gross_inr": "settled_gross", "refund_inr": "refunds", "fee_inr": "mdr_fees",
                               "net_inr": "settled_net"}, window, filters),
    }
