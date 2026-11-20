"""Deterministic checks between the planner and execution: names, values, scope, defaults.

Order matters: scope (refuse) beats everything, so an out-of-scope request is never "clarified" into running.
Every clarification option carries a plan_patch (top-level AnalysisPlan keys, JSON-able) that, merged into
the plan, makes it pass triage.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, get_args

from .config import load_catalog, persona as get_persona
from .contracts import (AnalysisPlan, Catalog, Clarification, ClarifyOption, DimensionDef, Filter, Refusal,
                        TimeWindow, WindowPreset)

DEFAULT_WINDOW = "last_7_days"
PREVIOUS_PRESET = {"last_7_days": "previous_7_days"}   # presets whose preceding window is itself a preset
DEFAULT_METRIC = {"reconcile": "settled_net", "data_quality": "attempts"}
NEEDS_BASELINE = ("compare_periods", "explain_change")


@dataclass
class TriageResult:
    action: Literal["proceed", "clarify", "refuse"]
    plan: AnalysisPlan
    clarification: Clarification | None = None
    refusal: Refusal | None = None
    variant_metrics: list[str] = field(default_factory=list)


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", str(s).lower()).strip()


def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _lookup(items, extra) -> dict[str, str]:
    """normalised alias -> canonical name, for metrics or dimensions."""
    out: dict[str, str] = {}
    for it in items:
        for alias in [it.name, it.label, *it.synonyms, *extra(it)]:
            out.setdefault(_key(alias), it.name)
    return out


def _resolve(name: str, table: dict[str, str]) -> tuple[str | None, list[str]]:
    """(canonical name or None, close matches as canonical names)."""
    k = _key(name)
    if k in table:
        return table[k], []
    close = difflib.get_close_matches(k, list(table), n=6, cutoff=0.6)
    return None, list(dict.fromkeys(table[c] for c in close))[:3]


def _norm_value(d: DimensionDef, v: str) -> str | None:
    v = str(v).strip()
    if d.dtype == "int":
        try:
            v = str(int(v))
        except ValueError:
            return None
    elif d.dtype == "date":
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            return None
    if d.values is None:
        return v or None
    by = {_compact(x): x for x in d.values}
    c = _compact(v)
    for cand in (c, c.removesuffix("bank"), c.removesuffix("s"), c.removesuffix("es")):
        if cand in by:
            return by[cand]
    return None


def _clarify(plan: AnalysisPlan, question: str, options: list[ClarifyOption]) -> TriageResult:
    return TriageResult("clarify", plan, clarification=Clarification(question=question, options=options))


def _filters_json(filters: list[Filter]) -> list[dict]:
    return [f.model_dump() for f in filters]


def _mentioned_regions(question: str, regions: list[str]) -> list[str]:
    return [r for r in regions if re.search(rf"\b{re.escape(r)}\b", question, re.IGNORECASE)]


def _scope_refusal(plan: AnalysisPlan, cat: Catalog, persona: str) -> TriageResult | None:
    """Refuse when the plan explicitly targets regions outside the persona's scope.

    An explicit region filter is what will run, so it decides; without one, region names in the question
    are the safety net for a planner that dropped the filter. A not_in filter only narrows, never widens.
    """
    p = get_persona(persona)
    region_dim = cat.dimension("region")
    aliases = {_key(a) for a in ("region", *region_dim.synonyms)}
    region_filters = [f for f in plan.filters if _key(f.dimension) in aliases]
    asked = [_norm_value(region_dim, v) or v for f in region_filters if f.op == "in" for v in f.values]
    if not any(f.op == "in" for f in region_filters):
        asked = _mentioned_regions(plan.question, region_dim.values or [])
    outside = sorted({r for r in asked if r not in p.regions})
    if not outside:
        return None
    mine = ", ".join(p.regions)
    reason = (f"{', '.join(outside)} {'is' if len(outside) == 1 else 'are'} outside your access: "
              f"{p.label} can see {mine} only.")
    refusal = Refusal(reason=reason, suggestion=f"I can answer the same question for {mine}.")
    if plan.route == "sql":   # the SQL text names the region; a filter patch cannot fix it
        return TriageResult("refuse", plan, refusal=refusal)
    if plan.route == "refuse" and plan.refuse_reason and not _mentioned_regions(plan.refuse_reason, outside):
        # the planner refused for another reason (forecast, PII...): scoping it down would not make it answerable
        return TriageResult("refuse", plan, refusal=Refusal(reason=f"{plan.refuse_reason} {reason}"))
    scoped = [f for f in plan.filters if f not in region_filters]
    scoped.append(Filter(dimension="region", op="in", values=list(p.regions)))
    patch = {"filters": _filters_json(scoped), "route": "catalog", "refuse_reason": None,
             "assumptions": [*plan.assumptions, f"Limited to {mine}, the regions you can see."]}
    refusal.plan_patch = patch
    return TriageResult("refuse", plan, refusal=refusal, clarification=Clarification(
        question=f"Answer for {mine} instead?",
        options=[ClarifyOption(label=f"Same question for {mine} only", plan_patch=patch)]))


def _from_ambiguities(plan: AnalysisPlan, cat: Catalog) -> list[ClarifyOption]:
    """Turn a planner-requested clarification into options we can apply without re-planning."""
    metrics = {m.name: m for m in cat.metrics}
    presets = get_args(WindowPreset)
    opts = []
    for a in plan.ambiguities:
        for o in a.options:
            if o in metrics:
                opts.append(ClarifyOption(label=metrics[o].label, plan_patch={"metric": o, "route": "catalog"}))
            elif o in presets:
                opts.append(ClarifyOption(label=o.replace("_", " "),
                                          plan_patch={"window": {"preset": o}, "route": "catalog"}))
    return opts


def triage(plan: AnalysisPlan, persona: str) -> TriageResult:
    cat = load_catalog()
    p = get_persona(persona)
    plan = plan.model_copy(deep=True)

    # ---- scope first: an explicit out-of-scope region is refused even if the planner wanted to clarify
    refused = _scope_refusal(plan, cat, persona)
    if refused:
        return refused
    if plan.route == "refuse":
        return TriageResult("refuse", plan, refusal=Refusal(
            reason=plan.refuse_reason or "The governed payments data cannot answer this question."))
    if plan.route == "clarify":
        return _clarify(plan, plan.clarify_question or "Could you say a bit more about what you need?",
                        _from_ambiguities(plan, cat))
    if plan.route == "sql":
        if not (plan.sql or "").strip():
            return _clarify(plan, "I couldn't map this to a governed metric. Could you rephrase it in terms of "
                                  "success rate, declines, volume, GMV or settlements?", [])
        return TriageResult("proceed", plan)

    # ---- catalog route: canonical names
    mtab = _lookup(cat.metrics, lambda m: [])
    dtab = _lookup(cat.dimensions, lambda d: [d.column])
    if plan.metric is None:
        if plan.intent in DEFAULT_METRIC:
            plan.metric = DEFAULT_METRIC[plan.intent]
        else:
            return _clarify(plan, "Which metric should I use?", [
                ClarifyOption(label=cat.metric(n).label, plan_patch={"metric": n})
                for n in ("success_rate", "gmv", "attempts")])
    name, close = _resolve(plan.metric, mtab)
    if name is None:
        return _clarify(plan, f"I don't know the metric '{plan.metric}'. Did you mean one of these?", [
            ClarifyOption(label=cat.metric(n).label, plan_patch={"metric": n}) for n in close])
    plan.metric = name
    metric = cat.metric(name)

    dims = []
    for i, d in enumerate(plan.dimensions):
        dn, close = _resolve(d, dtab)
        if dn is None:
            rest = [x for j, x in enumerate(plan.dimensions) if j != i]
            return _clarify(plan, f"I don't know the dimension '{d}'. Did you mean one of these?", [
                *(ClarifyOption(label=cat.dimension(c).label, plan_patch={"dimensions": rest[:i] + [c] + rest[i:]})
                  for c in close),
                ClarifyOption(label=f"Without '{d}'", plan_patch={"dimensions": rest})])
        dims.append(dn)
    plan.dimensions = list(dict.fromkeys(dims))

    filters: list[Filter] = []
    for i, f in enumerate(plan.filters):
        others = [x for j, x in enumerate(plan.filters) if j != i]
        dn, close = _resolve(f.dimension, dtab)
        if dn is None:
            return _clarify(plan, f"I can't filter on '{f.dimension}'. Did you mean one of these?", [
                *(ClarifyOption(label=cat.dimension(c).label, plan_patch={"filters": _filters_json(
                    others[:i] + [f.model_copy(update={"dimension": c})] + others[i:])}) for c in close),
                ClarifyOption(label=f"Without the '{f.dimension}' filter", plan_patch={"filters": _filters_json(others)})])
        dim = cat.dimension(dn)
        values = []
        for v in f.values:
            nv = _norm_value(dim, v)
            if nv is None:
                keep = [x for x in f.values if x != v]
                close = difflib.get_close_matches(str(v).upper(), dim.values or [], n=3, cutoff=0.5)
                fix = lambda vals: _filters_json(others[:i] + [f.model_copy(update={"dimension": dn, "values": vals})]
                                                 + others[i:]) if vals else _filters_json(others)
                return _clarify(plan, f"'{v}' is not a known {dim.label.lower()}. Did you mean one of these?", [
                    *(ClarifyOption(label=c, plan_patch={"filters": fix([*keep, c])}) for c in close),
                    ClarifyOption(label=f"Ignore '{v}'", plan_patch={"filters": fix(keep)})])
            values.append(nv)
        filters.append(Filter(dimension=dn, op=f.op, values=list(dict.fromkeys(values))))
    plan.filters = filters

    # ---- every dimension and filter must exist on the metric's table
    for dn in [*plan.dimensions, *(f.dimension for f in plan.filters)]:
        dim = cat.dimension(dn)
        if metric.table not in dim.tables:
            return _clarify(plan, f"{metric.label} comes from {metric.table}, which has no {dim.label.lower()}. "
                                  f"Continue without it?", [ClarifyOption(
                label=f"Without {dim.label.lower()}",
                plan_patch={"dimensions": [d for d in plan.dimensions if d != dn],
                            "filters": _filters_json([f for f in plan.filters if f.dimension != dn])})])

    # ---- default windows, each stated as an assumption
    if plan.window is None or (plan.window.preset is None and plan.window.start is None):
        plan.window = TimeWindow(preset=DEFAULT_WINDOW)
        plan.assumptions.append("No period was given, so the last 7 days were used.")
    if plan.intent in NEEDS_BASELINE and (plan.baseline is None or
                                          (plan.baseline.preset is None and plan.baseline.start is None)):
        prev = PREVIOUS_PRESET.get(plan.window.preset or "")
        plan.baseline = TimeWindow(preset=prev) if prev else None   # None: pipeline uses compiler.default_baseline
        plan.assumptions.append(f"Compared with the {prev.replace('_', ' ') if prev else 'preceding period of the same length'}.")
    if p.regions != (cat.dimension("region").values or []):
        note = f"Covers {', '.join(p.regions)} only (your access)."
        if note not in plan.assumptions:
            plan.assumptions.append(note)

    variants = [o for a in plan.ambiguities if a.kind == "denominator" for o in a.options
                if o != plan.metric and o in metric.variants]
    return TriageResult("proceed", plan, variant_metrics=list(dict.fromkeys(variants)))
