"""Vega-Lite v5 specs (plain dicts) for Evidence.chart and the UI. Deterministic chart choice, no LLM.

Style rules: Okabe-Ito colours (safe for the common colour-vision deficiencies), a title on every chart,
tooltips, ~700 px wide, and every bar carries a text label so nothing relies on colour alone.
Labels use contracts.format_value, the one place numbers become text; axis ticks use the matching
Vega expression from _axis_expr.
"""
from __future__ import annotations

import json
from typing import Any

from .contracts import DimensionDecomposition, ReconResult, ValueFormat, format_value

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
WIDTH = 620                      # plot area; with axes and labels the chart is ~700 px
OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]
MIX, RATE, TOTAL = "#0072B2", "#E69F00", "#595959"
DOWN, UP = "#D55E00", "#009E73"
GREY = "#BBBBBB"
STATUS = {"answered": UP, "clarify": RATE, "refused": TOTAL, "error": DOWN}   # run status -> colour


def _axis_expr(fmt: ValueFormat) -> str | None:
    """Vega expression that renders an axis tick (datum.value) like format_value."""
    v = "datum.value"
    return {
        "pct": f"format({v}, '.1%')",
        "pp": f"format({v} * 100, '+.1f') + ' pp'",
        "inr": f"({v} < 0 ? '-' : '') + '₹' + (abs({v}) >= 1e7 ? format(abs({v}) / 1e7, '.2f') + ' Cr' : "
               f"abs({v}) >= 1e5 ? format(abs({v}) / 1e5, '.2f') + ' L' : format(abs({v}), ',.0f'))",
        "int": f"format({v}, ',.0f')",
        "float": f"format({v}, '.3g')",
    }.get(fmt)


def _axis(fmt: ValueFormat, title: str) -> dict:
    expr = _axis_expr(fmt)
    return {"title": title, **({"labelExpr": expr} if expr else {})}


def _title(field: str) -> str:
    return field.replace("_", " ").capitalize()


def _rows(rows: list[dict], y: str, fmt: ValueFormat) -> list[dict]:
    """JSON-safe copies (dates -> ISO strings) with a formatted `_label` for text marks and tooltips."""
    safe = json.loads(json.dumps(rows, default=str))
    return [{**r, "_label": format_value(r.get(y), fmt)} for r in safe]


def _color(field: str, domain: list[str] | None = None, rng: list[str] = OKABE_ITO) -> dict:
    scale = {"range": rng, **({"domain": domain} if domain else {})}
    return {"field": field, "type": "nominal", "scale": scale, "legend": {"title": None, "orient": "top"}}


def _base(title: str | dict, values: list[dict]) -> dict:
    return {"$schema": SCHEMA, "title": title, "width": WIDTH, "data": {"values": values}}


def waterfall(dec: DimensionDecomposition, top_n: int = 6) -> dict:
    """Mix and rate effect per top segment, chained cumulatively, then total bars for mix, rate and the change."""
    top, rest = dec.segments[:top_n], dec.segments[top_n:]
    steps = [(f"{s.segment} · mix", "Mix effect", s.mix_effect) for s in top]
    if rest:
        steps.append(("Other segments · mix", "Mix effect", sum(s.mix_effect for s in rest)))
    steps += [(f"{s.segment} · rate", "Rate effect", s.rate_effect) for s in top]
    if rest:
        steps.append(("Other segments · rate", "Rate effect", sum(s.rate_effect for s in rest)))
    rows, cum = [], 0.0
    for label, kind, v in steps:
        rows.append((label, kind, cum, cum + v, v))
        cum += v
    rows += [("Mix total", "Total", 0.0, dec.mix_total, dec.mix_total),
             ("Rate total", "Total", 0.0, dec.rate_total, dec.rate_total),
             ("Change (Δ)", "Total", 0.0, dec.delta, dec.delta)]
    values = [{"step": s, "kind": k, "start": a, "end": b, "lo": min(a, b), "hi": max(a, b), "value": v,
               "_label": format_value(v, "pp")} for s, k, a, b, v in rows]
    lo, hi = min(min(r["lo"] for r in values), 0.0), max(max(r["hi"] for r in values), 0.0)
    pad = (hi - lo) * 0.22 or 0.001          # room for the outside labels
    x = {"type": "quantitative", "scale": {"domain": [lo - pad, hi + pad]},
         "axis": _axis("pp", "Contribution to the change (pp)")}
    y = {"field": "step", "type": "nominal", "sort": None, "title": None}
    title = {"text": f"Mix vs rate by {dec.dimension.replace('_', ' ')}",
             "subtitle": f"Δ {format_value(dec.delta, 'pp')} = mix {format_value(dec.mix_total, 'pp')} "
                         f"+ rate {format_value(dec.rate_total, 'pp')}"}
    label = lambda cond, align, dx, field: {  # noqa: E731
        "transform": [{"filter": cond}], "mark": {"type": "text", "align": align, "dx": dx},
        "encoding": {"y": y, "x": {**x, "field": field}, "text": {"field": "_label"}}}
    return {
        **_base(title, values),
        "height": {"step": 24},
        "layer": [
            {"mark": {"type": "bar"},
             "encoding": {"y": y, "x": {**x, "field": "start"}, "x2": {"field": "end"},
                          "color": _color("kind", ["Mix effect", "Rate effect", "Total"], [MIX, RATE, TOTAL]),
                          "tooltip": [{"field": "step", "title": "Step"}, {"field": "kind", "title": "Effect"},
                                      {"field": "_label", "title": "Contribution"}]}},
            label("datum.value >= 0", "left", 4, "hi"),
            label("datum.value < 0", "right", -4, "lo"),
            {"mark": {"type": "rule", "strokeDash": [4, 4]}, "encoding": {"x": {"datum": 0, "type": "quantitative"}}},
        ],
    }


def bars(rows: list[dict], x: str, y: str, fmt: ValueFormat, color: str | None = None) -> dict:
    values = _rows(rows, y, fmt)
    enc: dict[str, Any] = {
        "x": {"field": x, "type": "nominal", "sort": None, "title": _title(x), "axis": {"labelAngle": 0 if len(values) <= 8 else -40}},
        "y": {"field": y, "type": "quantitative", "axis": _axis(fmt, _title(y))},
        "tooltip": [{"field": x, "title": _title(x)}, *([{"field": color, "title": _title(color)}] if color else []),
                    {"field": "_label", "title": _title(y)}],
    }
    if color:
        enc["xOffset"] = {"field": color, "type": "nominal"}
    title = f"{_title(y)} by {x.replace('_', ' ')}" + (f" and {color.replace('_', ' ')}" if color else "")
    return {
        **_base(title, values),
        "encoding": enc,
        "layer": [
            {"mark": {"type": "bar"}, "encoding": {"color": _color(color)} if color else {}},
            {"mark": {"type": "text", "baseline": "bottom", "dy": -3, "fontSize": 11}, "encoding": {"text": {"field": "_label"}}},
        ],
    }


def trend(rows: list[dict], x: str, y: str, fmt: ValueFormat, color: str | None = None) -> dict:
    values = _rows(rows, y, fmt)
    first = values[0].get(x) if values else None
    xtype = "temporal" if isinstance(first, str) and first[:4].isdigit() and first[4:5] == "-" else "ordinal"
    enc: dict[str, Any] = {
        "x": {"field": x, "type": xtype, "title": _title(x)},
        "y": {"field": y, "type": "quantitative", "scale": {"zero": False}, "axis": _axis(fmt, _title(y))},
        "tooltip": [{"field": x, "title": _title(x), **({"type": "temporal"} if xtype == "temporal" else {})},
                    *([{"field": color, "title": _title(color)}] if color else []), {"field": "_label", "title": _title(y)}],
    }
    if color:  # dash pattern as a second channel so series differ without colour
        enc["color"] = _color(color)
        enc["strokeDash"] = {"field": color, "type": "nominal", "legend": None}
    return {**_base(f"{_title(y)} by {x.replace('_', ' ')}", values),
            "mark": {"type": "line", "point": True}, "encoding": enc}


def recon_bridge(recon: ReconResult) -> dict:
    """Transaction GMV, each reconciling component, settled net. The axis is truncated so components are visible."""
    rows = [("Transaction GMV", "Total", 0.0, recon.txn_gmv_inr, format_value(recon.txn_gmv_inr, "inr"))]
    cum = recon.txn_gmv_inr
    for c in recon.components:          # a positive component is money that does not reach the payout
        kind = "Reduces payout" if c.amount_inr > 0 else "Adds to payout" if c.amount_inr < 0 else "No effect"
        label = ("-" if c.amount_inr > 0 else "+") + format_value(abs(c.amount_inr), "inr")
        rows.append((_title(c.name), kind, cum, cum - c.amount_inr, label))
        cum -= c.amount_inr
    rows.append(("Settled net", "Total", 0.0, recon.settled_net_inr, format_value(recon.settled_net_inr, "inr")))
    points = [p for _, _, a, b, _ in rows for p in (a, b) if p]
    lo, hi = min(points), max(points)
    floor = max(0.0, lo - max(1.5 * (hi - lo), 0.02 * hi))
    values = [{"step": s, "kind": k, "start": a, "end": b, "top": max(a, b), "_label": lab} for s, k, a, b, lab in rows]
    y = {"type": "quantitative", "scale": {"domain": [floor, hi + 0.15 * (hi - floor)]},
         "axis": _axis("inr", "INR (axis starts above zero)")}
    xenc = {"field": "step", "type": "nominal", "sort": None, "title": None, "axis": {"labelAngle": 0}}
    return {
        **_base({"text": "From transaction GMV to settled net", "subtitle": recon.window}, values),
        "layer": [
            {"mark": {"type": "bar", "clip": True},
             "encoding": {"x": xenc, "y": {**y, "field": "start"}, "y2": {"field": "end"},
                          "color": _color("kind", ["Total", "Reduces payout", "Adds to payout", "No effect"],
                                          [TOTAL, DOWN, UP, GREY]),
                          "tooltip": [{"field": "step", "title": "Step"}, {"field": "_label", "title": "Amount"}]}},
            {"mark": {"type": "text", "baseline": "bottom", "dy": -3, "fontSize": 11},
             "encoding": {"x": xenc, "y": {**y, "field": "top"}, "text": {"field": "_label"}}},
        ],
    }


# ---------------------------------------------------------------- dashboard charts (Home, Eval, Runs)
# Rows arrive with their display text already in `_label` (formatted in Python); times are local ISO strings
# without an offset ("2026-11-21T15:30:00"), which Vega reads as wall-clock time in any browser.
# Time axes: a label whose tick sits within 40 px of an end aligns inward, so the last one never runs off the card
# (Vega's default flushes only a tick exactly at the end; Vega's fit-x sizing can still leave a later tick's label over).
TIME_AXIS = {"labelFlush": 40}


def _palette(field: str, colors: dict[str, str]) -> dict:
    enc = _color(field, list(colors), list(colors.values()))
    return {**enc, "legend": None} if len(colors) == 1 else enc


def sparkline(rows: list[dict], x: str, y: str) -> dict:
    """A 40 px line with no axes or title, for a KPI card (the card carries the label and value)."""
    return {"$schema": SCHEMA, "width": WIDTH, "height": 40, "padding": 2, "data": {"values": rows},
            "mark": {"type": "line", "color": MIX, "strokeWidth": 1.5, "interpolate": "monotone"},
            "encoding": {"x": {"field": x, "type": "temporal", "axis": None},
                         "y": {"field": y, "type": "quantitative", "axis": None, "scale": {"zero": False}}}}


def lines(rows: list[dict], x: str, y: str, title: str | dict, y_axis: dict, colors: dict[str, str],
          zero: bool = False, tooltip: list[dict] | None = None, x_format: str = "%d %b") -> dict:
    """Lines over time, one per row["series"] value (colours from `colors`, the first solid and the rest dashed)."""
    color = _palette("series", colors)
    if color["legend"]:   # a short line as the legend mark, so the dashed series shows its dash
        color = {**color, "legend": {**color["legend"], "symbolType": "stroke", "symbolStrokeWidth": 2}}
    enc = {"x": {"field": x, "type": "temporal", "title": None, "axis": {**TIME_AXIS, "format": x_format}},
           "y": {"field": y, "type": "quantitative", "scale": {"zero": zero}, "axis": y_axis},
           "color": color,   # one legend: Vega-Lite merges the two channels on the same field
           "strokeDash": {"field": "series", "type": "nominal", "scale": {"domain": list(colors)}, "legend": color["legend"]},
           "tooltip": tooltip or [{"field": x, "type": "temporal", "title": "Time", "format": "%d %b %H:%M"},
                                  {"field": "_label", "title": y_axis.get("title") or _title(y)}]}
    return {**_base(title, rows), "height": 200, "mark": {"type": "line", "point": {"size": 18}}, "encoding": enc}


def hbars(rows: list[dict], y: str, x: str, title: str | dict, x_axis: dict, colors: dict[str, str],
          group: str | None = None, x_max: float | None = None) -> dict:
    """Horizontal bars, each labelled with its `_label`. With `group` the bars of one `y` sit side by side,
    coloured by group value; without it, every bar takes the one colour in `colors`."""
    top = max([x_max or 0.0, *(r[x] for r in rows)]) or 1.0
    yenc = {"field": y, "type": "nominal", "sort": None, "title": None}
    enc: dict[str, Any] = {
        "y": yenc,
        "x": {"field": x, "type": "quantitative", "axis": x_axis, "scale": {"domain": [0, top * 1.2], "nice": False}},
        "tooltip": [{"field": y, "title": _title(y)}, *([{"field": group, "title": _title(group)}] if group else []),
                    {"field": "_label", "title": x_axis.get("title") or _title(x)}]}
    bar: dict[str, Any] = {"mark": {"type": "bar", "cornerRadiusEnd": 3}}
    if group:
        enc["yOffset"] = {"field": group, "type": "nominal", "scale": {"domain": list(colors)}}
        bar["encoding"] = {"color": _palette(group, colors)}   # bars only: the labels keep the text colour
    else:
        bar["mark"]["color"] = next(iter(colors.values()))
    # with group the step is per bar (Vega-Lite steps the offset band when yOffset is discrete)
    return {**_base(title, rows), "height": {"step": 18 if group else 24}, "encoding": enc,
            "layer": [bar,
                      {"mark": {"type": "text", "align": "left", "dx": 4, "fontSize": 11}, "encoding": {"text": {"field": "_label"}}}]}


def status_bars(rows: list[dict], x: str, time_unit: str, title: str | dict) -> dict:
    """Runs per time bucket (one row per run), stacked by status."""
    xenc = {"field": x, "timeUnit": time_unit, "type": "temporal"}
    hourly = "hours" in time_unit
    fmt = "%d %b %H:00" if hourly else "%d %b"
    # ticks at least one bucket apart: a half-hour tick would print the hour twice
    axis = {**TIME_AXIS, "format": fmt, "tickCount": {"interval": "hour" if hourly else "day"}}
    return {**_base(title, rows), "height": 160, "mark": {"type": "bar", "cornerRadiusEnd": 2},
            "encoding": {"x": {**xenc, "title": None, "axis": axis},
                         "y": {"aggregate": "count", "type": "quantitative", "title": "Runs",
                               "axis": {"format": "d", "tickMinStep": 1}},
                         "color": _palette("status", STATUS),
                         "tooltip": [{**xenc, "title": "From", "format": fmt}, {"field": "status", "title": "Status"},
                                     {"aggregate": "count", "type": "quantitative", "title": "Runs"}]}}


def status_points(rows: list[dict], x: str, y: str, title: str | dict, y_axis: dict, x_format: str = "%d %b") -> dict:
    """One point per run over time, coloured and shaped by status."""
    legend = {"title": None, "orient": "top"}
    return {**_base(title, rows), "height": 180, "mark": {"type": "point", "filled": True, "size": 46, "opacity": 0.85},
            "encoding": {"x": {"field": x, "type": "temporal", "title": None, "axis": {**TIME_AXIS, "format": x_format}},
                         "y": {"field": y, "type": "quantitative", "axis": y_axis},
                         "color": {**_palette("status", STATUS), "legend": legend},
                         "shape": {"field": "status", "type": "nominal", "scale": {"domain": list(STATUS)}, "legend": legend},
                         "tooltip": [{"field": x, "type": "temporal", "title": "Asked", "format": "%d %b %H:%M"},
                                     {"field": "status", "title": "Status"}, {"field": "_label", "title": y_axis["title"]}]}}
