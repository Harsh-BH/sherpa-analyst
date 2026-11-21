"""Home overview: four KPIs, last 30 days vs the 30 before, through the governed path only
(compile_metric -> guard -> db.run_query as the persona's role, so RLS scopes it). No LLM, no app.runs write."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from statistics import mean, stdev
from typing import Literal

from pydantic import BaseModel

from app.answer_extras import HINT, completeness_question, tone
from app.view import ChartView
from sherpa import charts, db, dq
from sherpa.compiler import compile_dq_queries, compile_metric, default_baseline, metric_value, resolve_window
from sherpa.config import load_catalog
from sherpa.contracts import CATALOG_FORMAT, DQWarning, TimeWindow, format_value

KPIS = ("success_rate", "gmv", "attempts", "technical_decline_rate")
# A day is unusual when |z| >= Z_UNUSUAL against the last 30 days' own daily mean and sample standard deviation
# (about 1 day in 20 if day-to-day noise were normal); it gets a larger red point on the trend.
Z_UNUSUAL = 2.0
CURRENT, PREVIOUS = "Last 30 days", "Previous 30 days"


class Kpi(BaseModel):
    key: str
    label: str
    value: str
    delta: str                                        # vs the previous 30 days: pp for rates, % change otherwise
    direction: Literal["up", "down", "flat"]
    tone: Literal["positive", "negative", "neutral"]  # judged by the metric's higher_is_better
    summary: str                                      # text alternative for the card and its sparkline
    spark: dict


class DayAsk(BaseModel):
    label: str        # "16 Nov · 90.1%"
    question: str


class OverviewOk(BaseModel):
    available: Literal[True] = True
    persona: str
    as_of: str
    window: str
    baseline: str
    kpis: list[Kpi]
    trend: ChartView
    unusual: list[DayAsk] = []   # the trend's unusual days as buttons: the keyboard's way to ask about them


class DataIssue(BaseModel):
    check: str
    severity: Literal["info", "warn", "error"]
    when: str         # "16 Nov", or the window for a window-wide issue
    text: str         # dq's own code-built sentence
    question: str     # what a click asks


class DataHealth(BaseModel):
    """The rail's "Data health · last 30 days": the governed dq checks over the window, as the persona."""
    available: Literal[True] = True
    persona: str
    window: str
    issues: list[DataIssue]


class OverviewUnavailable(BaseModel):
    available: Literal[False] = False
    reason: str


def numbers(persona: str, as_of: date, data_start: date) -> tuple[TimeWindow, TimeWindow, dict]:
    """Raw values: metric -> {"value", "prev", "daily": [(date, v)], "prev_daily": [(date, v)]}."""
    window = resolve_window(TimeWindow(preset="last_30_days"), as_of, data_start)
    baseline = resolve_window(default_baseline(window), as_of, data_start)
    out = {}
    for m in KPIS:
        df = db.run_query(compile_metric(m, window=window, baseline=baseline, grain="day"), persona).df
        cur, prev = df[df.period == "current"], df[df.period == "baseline"]
        out[m] = {"value": metric_value(m, cur.num.sum(), cur.den.sum()),
                  "prev": metric_value(m, prev.num.sum(), prev.den.sum()),
                  **{k: [(d, metric_value(m, n, c)) for d, n, c in f[["bucket_date", "num", "den"]].itertuples(index=False)]
                     for k, f in (("daily", cur), ("prev_daily", prev))}}
    return window, baseline, out


def _day(d: date) -> str:
    return f"{d.isoformat()}T00:00:00"   # local midnight: a bare date would be read as UTC


def _kpi(key: str, n: dict) -> Kpi:
    m = load_catalog().metric(key)
    fmt, cur, prev = CATALOG_FORMAT[m.format], n["value"], n["prev"]
    if cur is None or prev is None or (fmt != "pct" and not prev):
        delta, diff = "n/a", 0.0
    else:
        diff = cur - prev
        delta = format_value(diff, "pp") if fmt == "pct" else f"{diff / prev:+.1%}"
    direction = "flat" if not any(c in "123456789" for c in delta) else "up" if diff > 0 else "down"
    value = format_value(cur, fmt)
    rows = [{"day": _day(d), "value": v} for d, v in n["daily"] if v is not None]
    return Kpi(key=key, label=m.label, value=value, delta=delta, direction=direction, tone=tone(direction, m.higher_is_better),
               summary=f"{m.label} {value}, {delta} vs the previous 30 days", spark=charts.sparkline(rows, "day", "value"))


def _moves(n: dict) -> list[dict]:
    """Each current day with a value: its change vs the day before (the previous period supplies the first day's,
    None when unknown), the question that asks why, and whether it is unusual (Z_UNUSUAL)."""
    known = {d: v for d, v in [*n["prev_daily"], *n["daily"]] if v is not None}
    days = [(d, v) for d, v in n["daily"] if v is not None]
    vals = [v for _, v in days]
    mu, sd = (mean(vals), stdev(vals)) if len(vals) >= 3 else (0.0, 0.0)
    out = []
    for d, v in days:
        before = known.get(d - timedelta(days=1))
        change = None if before is None else v - before
        verb = "fall" if change and change < 0 else "rise" if change else None
        out.append({"day": d, "value": v, "change": change, "unusual": bool(sd) and abs(v - mu) / sd >= Z_UNUSUAL,
                    "ask": verb and f"Why did success rate {verb} on {dq._d(d)} compared with the day before?"})
    return out


def _unusual(n: dict) -> list[DayAsk]:
    return [DayAsk(label=f"{dq._d(m['day'])} · {format_value(m['value'], 'pct')}", question=m["ask"])
            for m in _moves(n) if m["unusual"] and m["ask"]]


def _trend(window: TimeWindow, baseline: TimeWindow, n: dict) -> ChartView:
    shift = window.end - baseline.end              # the previous period drawn under the current one, day for day
    moves = _moves(n)
    rows = []
    for m in moves:
        hint = ("Unusual day. " if m["unusual"] else "") + (HINT if m["ask"] else "No day before to compare with")
        rows.append({"day": _day(m["day"]), "date": _day(m["day"]), "series": CURRENT, "value": m["value"],
                     "_label": format_value(m["value"], "pct"), "_change": format_value(m["change"], "pp"),
                     "_unusual": m["unusual"], "_hint": hint, **({"_ask": m["ask"]} if m["ask"] else {})})
    rows += [{"day": _day(d + shift), "date": _day(d), "series": PREVIOUS, "value": v, "_label": format_value(v, "pct")}
             for d, v in n["prev_daily"] if v is not None]
    now = [r for r in rows if r["series"] == CURRENT]   # the daily range quoted is the last 30 days' own
    lo, hi = (min(now, key=lambda r: r["value"]), max(now, key=lambda r: r["value"])) if now else (None, None)
    # two subtitle lines: Vega never wraps, and one line loses the baseline's end on a phone
    spec = charts.lines(rows, "day", "value", {"text": "Daily success rate", "subtitle": [window.label, f"vs {baseline.label}"]},
                        charts._axis("pct", "Success rate"), {CURRENT: charts.MIX, PREVIOUS: charts.TOTAL},
                        tooltip=[{"field": "series", "title": "Period"},
                                 {"field": "date", "type": "temporal", "title": "Date", "format": "%d %b %Y"},
                                 {"field": "_label", "title": "Success rate"}])
    # Vega picks a line's first point for a click anywhere on the line, so the line carries no question;
    # the current period's points, drawn over it, do (`_ask`, pointer cursor), unusual days larger and red.
    spec["layer"] = [
        {"mark": spec.pop("mark"), "transform": [{"calculate": "null", "as": "_ask"}]},
        {"name": "ask_points", "transform": [{"filter": {"field": "series", "equal": CURRENT}}],
         "mark": {"type": "point", "filled": True, "opacity": 1, "cursor": "pointer"},
         "encoding": {"size": {"condition": {"test": "datum._unusual", "value": 90}, "value": 30},
                      "color": {"condition": {"test": "datum._unusual", "value": charts.DOWN}, "value": charts.MIX},
                      "tooltip": [{"field": "date", "type": "temporal", "title": "Date", "format": "%d %b %Y"},
                                  {"field": "_label", "title": "Success rate"},
                                  {"field": "_change", "title": "vs day before"},
                                  {"field": "_hint", "title": "Tip"}]}},
    ]
    flagged = ", ".join(f"{dq._d(m['day'])} {format_value(m['value'], 'pct')}" for m in moves if m["unusual"])
    rule = f"|z| ≥ {Z_UNUSUAL:g} against the last 30 days' daily mean and standard deviation"
    summary = (f"Daily success rate, {window.label}: {format_value(n['value'], 'pct')} overall"
               + (f", from {lo['_label']} to {hi['_label']} a day" if now else "")
               + f"; previous 30 days {format_value(n['prev'], 'pct')}. "
               + (f"Unusual days ({rule}): {flagged}." if flagged else f"No unusual days ({rule})."))
    return ChartView(key="overview-trend", title="Daily success rate", summary=summary, spec=spec)


@lru_cache(maxsize=8)
def _build(persona: str, version: str, as_of: date, data_start: date) -> OverviewOk:
    window, baseline, n = numbers(persona, as_of, data_start)
    return OverviewOk(persona=persona, as_of=f"{as_of:%d %b %Y}", window=window.label, baseline=baseline.label,
                      kpis=[_kpi(k, n[k]) for k in KPIS], trend=_trend(window, baseline, n["success_rate"]),
                      unusual=_unusual(n["success_rate"]))


def build(persona: str) -> OverviewOk:
    """Cached per (persona, data_version): a reseed changes the version and so the key."""
    v = db.data_version(persona)
    return _build(persona, v["version"], v["as_of"], v["data_start"])


def _issue(w: DQWarning, window: TimeWindow) -> DataIssue:
    day = w.values.get("date") or str(w.values.get("start") or "")[:10]   # duplicates: date; an outage: its start
    when = dq._d(date.fromisoformat(day)) if day else f"{dq._d(window.start)} – {dq._d(window.end)}"
    return DataIssue(check=w.check, severity=w.severity, when=when, text=w.message,
                     question=completeness_question(when if day else "last 30 days"))


@lru_cache(maxsize=8)
def _health(persona: str, version: str, as_of: date, data_start: date) -> DataHealth:
    window = resolve_window(TimeWindow(preset="last_30_days"), as_of, data_start)
    qs = compile_dq_queries(window)   # no filters: the persona's role and RLS scope the rows
    found = dq.run_checks(db.run_query(qs["dq_daily"], persona).df, db.run_query(qs["hourly"], persona).df,
                          window=window, as_of=as_of)
    return DataHealth(persona=persona, window=window.label, issues=[_issue(w, window) for w in found])


def data_health(persona: str) -> DataHealth:
    """Cached per (persona, data_version), like build."""
    v = db.data_version(persona)
    return _health(persona, v["version"], v["as_of"], v["data_start"])
