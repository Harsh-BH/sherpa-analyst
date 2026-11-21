"""Explore mode's plan building: a form in, a governed AnalysisPlan and its question text out. No LLM."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from sherpa.config import load_catalog
from sherpa.contracts import AnalysisPlan, Filter, Intent, TimeWindow, WindowPreset


class ExploreForm(BaseModel):
    intent: Intent
    metric: str
    dimensions: list[str] = []
    window: WindowPreset = "last_7_days"
    baseline: WindowPreset | None = None
    grain: Literal["day", "hour"] = "day"
    filters: list[Filter] = []


def _words(s: str) -> str:
    return s.replace("_", " ")


def build_explore_plan(form: ExploreForm) -> tuple[str, AnalysisPlan]:
    """Raises ValueError for an unknown metric or dimension (the API turns it into a 422)."""
    catalog = load_catalog()
    try:
        metric = catalog.metric(form.metric)
        labels = {n: catalog.dimension(n).label for n in [*form.dimensions, *(f.dimension for f in form.filters)]}
    except KeyError as e:
        raise ValueError(e.args[0]) from None
    parts = [_words(form.intent).capitalize() + ":", metric.label]
    if form.dimensions:
        parts.append("by " + ", ".join(labels[d] for d in form.dimensions))
    parts.append(_words(form.window))
    if form.baseline:
        parts.append("vs " + _words(form.baseline))
    if form.filters:
        parts.append("where " + "; ".join(f"{labels[f.dimension]} in {', '.join(f.values)}" for f in form.filters))
    if form.intent == "trend":
        parts.append(f"by {form.grain}")
    question = " ".join(parts)
    plan = AnalysisPlan(question=question, route="catalog", intent=form.intent, metric=metric.name,
                        dimensions=form.dimensions, filters=form.filters, window=TimeWindow(preset=form.window),
                        baseline=TimeWindow(preset=form.baseline) if form.baseline else None, grain=form.grain)
    return question, plan
