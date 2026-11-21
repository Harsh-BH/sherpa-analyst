"""Display-ready view of an AnswerBundle: every number is already a string, so the UI only draws.

Ported from the former Streamlit renderer (app/render.py), so tables and charts read as they did there."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel

from sherpa import charts
from sherpa.config import load_access, load_catalog
from sherpa.contracts import AnswerBundle, DimensionDecomposition, Evidence, SegmentEffect, format_value

STAGES = ("plan", "triage", "analysis", "dq", "narrate", "check")
STAGE_LABELS = {"plan": "Plan", "triage": "Triage", "analysis": "Analysis", "dq": "Data-quality checks",
                "narrate": "Narration", "check": "Claim check"}   # as the web trace names them


class KV(BaseModel):
    label: str
    value: str


class Table(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class ClaimView(BaseModel):
    n: int
    kind: Literal["fact", "hypothesis", "recommendation", "caveat"]
    text: str
    ok: bool
    problems: list[str]
    evidence_ids: list[str]
    missing_ids: list[str]


class EvidenceView(BaseModel):
    id: str
    title: str
    kind: str
    meta: list[KV]
    sql: list[KV]
    values: list[KV]
    table: Table | None
    chart: dict | None
    cited_by: list[int]


class ChartView(BaseModel):
    """A dashboard chart: `summary` is its text alternative (aria-label), `key` a stable id for the page."""
    key: str
    title: str
    summary: str
    spec: dict


class KeyChart(BaseModel):
    dimension: str
    label: str
    spec: dict
    simpson: str | None
    summary: str


class DriverSection(BaseModel):
    heading: str
    tables: list[tuple[str, Table]]
    drilldown: Table | None
    notes: list[str]


class ReconView(BaseModel):
    spec: dict
    components: Table
    source_of_truth: str


class StageTime(KV):
    fraction: float | None   # share of the total, for the trace's timing bar width; never displayed as a number


class Footprint(BaseModel):
    items: list[KV]
    stages: list[StageTime]
    summary: str


class View(BaseModel):
    partial: bool = False   # the numbers before the narrative: no headline, claims or confidence yet (SSE `partial`)
    claims: list[ClaimView]
    evidence: list[EvidenceView]
    key_charts: list[KeyChart]
    default_dimension: str | None
    fallback_chart: KV | None
    drivers: DriverSection | None
    recon: ReconView | None
    footprint: Footprint
    as_of: str | None


def fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "n/a"
    return f"{ms:.0f} ms" if ms < 100 else f"{ms / 1000:.1f} s"


def _cell(v: Any) -> str:
    return "" if v is None else str(v)


def _num(v: Any) -> float | None:
    """pandas.to_numeric(errors='coerce') for one cell; None when it is not a finite number."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _is_percent(metric: str | None) -> bool:
    try:
        return load_catalog().metric(metric).format == "percent"
    except KeyError:
        return False


def evidence_table(e: Evidence, percent_metric: bool = False) -> Table | None:
    """Result table rendered like the claims. A column takes Evidence.formats[col] or the format of any
    `<segkey>_<col>` key; failing that, 0..1 columns named *rate* (or `value` on a percent metric) are pct
    and *_inr columns are inr. Non-numeric columns are left as they are."""
    if not e.table:
        return None
    cols = list(dict.fromkeys(k for r in e.table for k in r))
    out = [[_cell(r.get(c)) for c in cols] for r in e.table]
    for j, name in enumerate(cols):
        raw = [r.get(name) for r in e.table]
        nums = [_num(v) for v in raw]
        if any(n is None for n in nums):
            continue
        fmt = e.formats.get(name) or next((f for k, f in e.formats.items() if k.endswith(f"_{name}")), None)
        if fmt is None and ("rate" in name or (name == "value" and percent_metric)) and all(0 <= n <= 1 for n in nums):
            fmt = "pct"
        elif fmt is None and name.endswith("_inr"):
            fmt = "inr"
        if fmt and fmt not in ("text", "date"):
            for row, n in zip(out, nums):
                row[j] = format_value(n, fmt)
    return Table(columns=cols, rows=out)


def value_text(e: Evidence, key: str) -> str:
    v = e.values[key]
    return format_value(v, e.formats.get(key, "text" if isinstance(v, str) else "float"))


def evidence_meta(e: Evidence) -> list[KV]:
    rows = [("Window", e.window), ("Baseline", e.baseline), ("Filters", ", ".join(e.filters) or "none"),
            ("Tables", ", ".join(e.tables)), ("Rows", e.row_count)]
    return [KV(label=k, value=str(v)) for k, v in rows if v is not None]


def sql_blocks(e: Evidence) -> list[KV]:
    return [KV(label=f"SQL {i + 1} of {len(e.sql)} · sha256 {e.sql_hashes[i] if i < len(e.sql_hashes) else 'n/a'}",
               value=s) for i, s in enumerate(e.sql)]


def _effects_table(effects: list[tuple[str, SegmentEffect]]) -> Table:
    def pct(v): return "" if v is None else f"{v * 100:.1f}%"
    def pp(v): return f"{v * 100:+.2f} pp"
    def yn(v): return "yes" if v else "no"
    return Table(
        columns=["segment", "share before", "share now", "rate before", "rate now", "mix (pp)", "rate (pp)",
                 "total (pp)", "z", "q (BH)", "supported", "significant", "material"],
        rows=[[label, pct(e.share0), pct(e.share1), pct(e.rate0), pct(e.rate1), pp(e.mix_effect), pp(e.rate_effect),
               pp(e.total_effect), "" if e.z is None else f"{e.z:.2f}", "" if e.q_value is None else f"{e.q_value:.2g}",
               yn(e.supported), yn(e.significant), yn(e.material)] for label, e in effects])


def _dim_label(name: str) -> str:
    try:
        return load_catalog().dimension(name).label
    except KeyError:
        return name.replace("_", " ")


def simpson_callout(dec: DimensionDecomposition) -> str | None:
    if not dec.simpson_flag:
        return None
    dim = dec.dimension.replace("_", " ")
    toward = "lower" if dec.mix_total < 0 else "higher"
    return (f"Simpson's paradox. The overall rate moved {format_value(dec.delta, 'pp')}, but "
            f"{format_value(dec.mix_total, 'pp')} of it is mix (volume moved toward {toward}-rate {dim} values) "
            f"and only {format_value(dec.rate_total, 'pp')} is rate change within them, so no {dim} got worse.")


def _driver_section(b: AnswerBundle) -> DriverSection:
    d = b.drivers
    try:
        metric = load_catalog().metric(d.metric).label
    except KeyError:
        metric = d.metric
    tables = [(f"{dec.dimension.replace('_', ' ')} · explanatory score {dec.score:.2f}"
               + (" · Simpson flag" if dec.simpson_flag else ""),
               _effects_table([(s.segment, s) for s in dec.segments])) for dec in d.dimensions]
    drill = _effects_table([(" × ".join(f"{k}={v}" for k, v in c.dims.items()), c.effect) for c in d.drilldown]) \
        if d.drilldown else None
    return DriverSection(
        heading=f"Segments · {metric}: {format_value(d.r0, 'pct')} → {format_value(d.r1, 'pct')} "
                f"({format_value(d.delta, 'pp')}), {d.window} vs {d.baseline}",
        tables=tables, drilldown=drill, notes=list(d.notes))


def _footprint(b: AnswerBundle) -> Footprint:
    t, u = b.timings_ms, b.llm_usage
    try:
        persona = load_access().persona(b.persona).label
    except KeyError:
        persona = b.persona
    cost = u.get("cost_usd") if isinstance(u.get("cost_usd"), int | float) else None
    llm = " · ".join(x for x in (u.get("backend"), cost is not None and f"${cost:.4f}") if x)
    cache = f"{t['cache_hits']} of {t['queries']} queries" if "queries" in t and "cache_hits" in t else None
    pairs = [("Run", b.run_id), ("Persona", persona), ("Data", b.data_version),
             ("As of", b.as_of and f"{b.as_of:%d %b %Y}"), ("Total", "total" in t and fmt_ms(t["total"])),
             ("LLM", llm), ("Cache", cache)]
    total = t.get("total") or None
    stages = [StageTime(label=s, value=fmt_ms(t[s]), fraction=total and min(t[s] / total, 1.0)) for s in STAGES if s in t]
    summary = " · ".join(x for x in (stages and f"{len(stages)} steps", "total" in t and fmt_ms(t["total"]),
                                     cost is not None and f"${cost:.4f}") if x)
    return Footprint(items=[KV(label=k, value=v) for k, v in pairs if v], stages=stages, summary=summary)


def build_view(b: AnswerBundle, *, partial: bool = False) -> View:
    ids = {e.id for e in b.evidence}
    claims, cited = [], {e.id: [] for e in b.evidence}
    for n, c in enumerate(b.claims, 1):
        uniq = list(dict.fromkeys(c.evidence_ids))
        for i in uniq:
            if i in ids:
                cited[i].append(n)
        claims.append(ClaimView(n=n, kind=c.kind, text=c.rendered, ok=c.ok, problems=list(c.problems),
                                evidence_ids=[i for i in uniq if i in ids], missing_ids=[i for i in uniq if i not in ids]))
    pct = _is_percent(b.plan.metric if b.plan else None)
    evidence = [EvidenceView(id=e.id, title=e.title, kind=e.kind, meta=evidence_meta(e), sql=sql_blocks(e),
                             values=[KV(label=f"{{{e.id}.{k}}}", value=value_text(e, k)) for k in e.values],
                             table=evidence_table(e, pct), chart=e.chart, cited_by=cited[e.id]) for e in b.evidence]
    dims = b.drivers.dimensions if b.drivers else []
    key_charts = [KeyChart(dimension=d.dimension, label=_dim_label(d.dimension), spec=charts.waterfall(d),
                           simpson=simpson_callout(d),
                           summary=f"By {_dim_label(d.dimension).lower()}: mix {format_value(d.mix_total, 'pp')}, "
                                   f"rate {format_value(d.rate_total, 'pp')}.") for d in dims]
    fallback = None
    if not dims and not b.recon:
        if e := next((e for e in b.evidence if e.chart), None):
            fallback = KV(label=f"{e.id} · {e.title}", value=e.id)
    recon = None
    if b.recon:
        recon = ReconView(spec=charts.recon_bridge(b.recon), source_of_truth=b.recon.source_of_truth,
                          components=Table(columns=["component", "amount", "note"],
                                           rows=[[c.name.replace("_", " "), format_value(c.amount_inr, "inr"), c.note]
                                                 for c in b.recon.components]))
    return View(partial=partial, claims=claims, evidence=evidence, key_charts=key_charts,
                default_dimension=b.drivers.top_dimension if b.drivers and b.drivers.top_dimension in
                {k.dimension for k in key_charts} else None,
                fallback_chart=fallback, drivers=_driver_section(b) if b.drivers else None, recon=recon,
                footprint=_footprint(b), as_of=f"{b.as_of:%d %b %Y}" if b.as_of else None)
