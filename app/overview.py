"""Home overview: four KPIs, last 30 days vs the 30 before, through the governed path only
(compile_metric -> guard -> db.run_query as the persona's role, so RLS scopes it). No LLM, no app.runs write."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from app.view import ChartView
from sherpa import charts, db
from sherpa.compiler import compile_metric, default_baseline, metric_value, resolve_window
from sherpa.config import load_catalog
from sherpa.contracts import CATALOG_FORMAT, TimeWindow, format_value

KPIS = ("success_rate", "gmv", "attempts", "technical_decline_rate")


class Kpi(BaseModel):
    key: str
    label: str
    value: str
    delta: str                                        # vs the previous 30 days: pp for rates, % change otherwise
    direction: Literal["up", "down", "flat"]
    tone: Literal["positive", "negative", "neutral"]  # judged by the metric's higher_is_better
    summary: str                                      # text alternative for the card and its sparkline
    spark: dict


class OverviewOk(BaseModel):
    available: Literal[True] = True
    persona: str
    as_of: str
    window: str
    baseline: str
    kpis: list[Kpi]
    trend: ChartView


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
    tone = "neutral" if direction == "flat" else "positive" if (direction == "up") == m.higher_is_better else "negative"
    value = format_value(cur, fmt)
    rows = [{"day": _day(d), "value": v} for d, v in n["daily"] if v is not None]
    return Kpi(key=key, label=m.label, value=value, delta=delta, direction=direction, tone=tone,
               summary=f"{m.label} {value}, {delta} vs the previous 30 days", spark=charts.sparkline(rows, "day", "value"))


def _trend(window: TimeWindow, baseline: TimeWindow, n: dict) -> ChartView:
    shift = window.end - baseline.end              # the previous period drawn under the current one, day for day
    cur, prev = "Last 30 days", "Previous 30 days"
    rows = [{"day": _day(d), "date": _day(d), "series": cur, "value": v, "_label": format_value(v, "pct")}
            for d, v in n["daily"] if v is not None]
    rows += [{"day": _day(d + shift), "date": _day(d), "series": prev, "value": v, "_label": format_value(v, "pct")}
             for d, v in n["prev_daily"] if v is not None]
    now = [r for r in rows if r["series"] == cur]   # the daily range quoted is the last 30 days' own
    lo, hi = (min(now, key=lambda r: r["value"]), max(now, key=lambda r: r["value"])) if now else (None, None)
    # two subtitle lines: Vega never wraps, and one line loses the baseline's end on a phone
    spec = charts.lines(rows, "day", "value", {"text": "Daily success rate", "subtitle": [window.label, f"vs {baseline.label}"]},
                        charts._axis("pct", "Success rate"), {cur: charts.MIX, prev: charts.TOTAL},
                        tooltip=[{"field": "series", "title": "Period"},
                                 {"field": "date", "type": "temporal", "title": "Date", "format": "%d %b %Y"},
                                 {"field": "_label", "title": "Success rate"}])
    summary = (f"Daily success rate, {window.label}: {format_value(n['value'], 'pct')} overall"
               + (f", from {lo['_label']} to {hi['_label']} a day" if now else "")
               + f"; previous 30 days {format_value(n['prev'], 'pct')}.")
    return ChartView(key="overview-trend", title="Daily success rate", summary=summary, spec=spec)


@lru_cache(maxsize=8)
def _build(persona: str, version: str, as_of: date, data_start: date) -> OverviewOk:
    window, baseline, n = numbers(persona, as_of, data_start)
    return OverviewOk(persona=persona, as_of=f"{as_of:%d %b %Y}", window=window.label, baseline=baseline.label,
                      kpis=[_kpi(k, n[k]) for k in KPIS], trend=_trend(window, baseline, n["success_rate"]))


def build(persona: str) -> OverviewOk:
    """Cached per (persona, data_version): a reseed changes the version and so the key."""
    v = db.data_version(persona)
    return _build(persona, v["version"], v["as_of"], v["data_start"])
