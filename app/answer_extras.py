"""What the view adds to an answer, all deterministic (no LLM): follow-up questions, drill questions on the
waterfall's segment bars, the headline split into chips, and the answer as Markdown for "Copy answer".

Question text is built here from catalog labels and the bundle's own window labels, so a follow-up names only
governed metrics, dimensions and values, and its plan (sent with the question) runs without the planner."""
from __future__ import annotations

import copy
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from sherpa.compiler import resolve_window
from sherpa.config import load_access, load_catalog
from sherpa.contracts import AnalysisPlan, AnswerBundle, DimensionDecomposition, Filter, TimeWindow

Tone = Literal["positive", "negative", "neutral"]
MAX_FOLLOW_UPS = 4
HINT = "Click to ask Sherpa why"
KEY_COLUMNS = ["segment", "share before", "share now", "rate before", "rate now", "total (pp)"]


class FollowUp(BaseModel):
    label: str            # the chip
    question: str         # what the run is asked as (and what history shows)
    plan: AnalysisPlan    # sent with the question, so the follow-up runs exactly as built, without the planner


class HeadlinePart(BaseModel):
    text: str
    kind: Literal["text", "value", "up", "down"]   # up / down: a signed, non-zero delta
    tone: Tone            # up / down judged by the metric's higher_is_better; neutral otherwise


def tone(direction: str, higher_is_better: bool) -> Tone:
    """Good news or bad: up on a higher-is-better metric is positive, down on one is negative (Home KPIs too)."""
    if direction not in ("up", "down"):
        return "neutral"
    return "positive" if (direction == "up") == higher_is_better else "negative"


# ------------------------------------------------------------------ phrasing
def _lower(label: str) -> str:
    """'Success rate' -> 'success rate'; an acronym ('GMV', 'MDR fees') keeps its case."""
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


def dim_label(name: str) -> str:
    """A dimension's catalog label ('Payment method'); its name, spaced, when the catalog lacks it."""
    try:
        return load_catalog().dimension(name).label
    except KeyError:
        return name.replace("_", " ")


def _dim(name: str) -> str:
    return _lower(dim_label(name))


def _in(label: str) -> str:
    """A window label as a phrase: 'in the last 7 days (13-19 Nov 2026)', 'yesterday (19 Nov 2026)',
    'across all data (1 Aug - 19 Nov 2026)', 'on 13 Nov 2026', 'during 6-12 Nov 2026'."""
    if label[:1].isdigit():
        return f"during {label}" if "-" in label else f"on {label}"
    if label.startswith("yesterday"):
        return label
    return f"across {label}" if label.startswith("all data") else f"in the {label}"


def completeness_question(window: str) -> str:
    """The data-quality question for a window label or a date: 'Is the transaction data for the last 7 days (...)
    complete?', '... for 18 Nov complete?', '... for yesterday (...) complete?' (the home rail asks it too)."""
    if window.startswith("all data"):
        return f"Is all the transaction data {window.removeprefix('all data ')} complete?"
    bare = window[:1].isdigit() or window.startswith("yesterday")
    return f"Is the transaction data for {window if bare else 'the ' + window} complete?"


def _range(start: date, end: date) -> str:
    return resolve_window(TimeWindow(start=start, end=end), as_of=end, data_start=start).label


def _drillable(dimension: str, segment: str) -> bool:
    """A segment a plan can filter on: a closed-vocabulary value of a catalog dimension ('Other segments' is not)."""
    try:
        return segment in (load_catalog().dimension(dimension).values or [])
    except KeyError:
        return False


def drill_question(metric_label: str, dimension: str, segment: str, window: str) -> str:
    return f"Why did {_lower(metric_label)} change for {_dim(dimension)} {segment} {_in(window)}?"


def drillable_waterfall(spec: dict, dec: DimensionDecomposition, metric_label: str, window: str) -> dict:
    """The waterfall with `_ask` on each segment's mix and rate bars (not 'Other segments', not the totals). Those bars
    are drawn again on top, alone, with a pointer cursor and a tooltip hint: a hint field on every bar would print
    'undefined' on the rest. Changes `spec` in place: charts.waterfall builds a fresh dict."""
    segments = {f"{s.segment} · {part}": s.segment for s in dec.segments if _drillable(dec.dimension, s.segment)
                for part in ("mix", "rate")}
    for row in spec["data"]["values"]:
        if seg := segments.get(row["step"]):
            row["_ask"] = drill_question(metric_label, dec.dimension, seg, window)
            row["_segment"], row["_hint"] = seg, HINT   # _segment: the keyboard path's button text (key-chart.tsx)
    hot = copy.deepcopy(spec["layer"][0])
    hot["transform"] = [{"filter": "isValid(datum._ask)"}]
    hot["mark"]["cursor"] = "pointer"
    hot["encoding"]["tooltip"].append({"field": "_hint", "title": "Drill down"})
    spec["layer"].insert(1, hot)
    return spec


# ------------------------------------------------------------------ follow-ups
def follow_ups(b: AnswerBundle) -> list[FollowUp]:
    """Up to four next questions for an answered catalog-route bundle, best first: drill the top driver segment by the
    next-best dimension, the same question for the top-moving region (only one the persona sees), explain or compare
    a single number, the day-by-day trend behind a change, and a completeness check when data quality flagged."""
    p = b.plan
    if b.status != "answered" or p is None or p.route != "catalog" or not p.metric or p.window is None:
        return []
    cat = load_catalog()
    try:
        metric = cat.metric(p.metric)
        regions = load_access().persona(b.persona).regions
    except KeyError:
        return []
    m, win = _lower(metric.label), p.window.label or (p.window.preset or "").replace("_", " ")
    out: list[FollowUp] = []

    def add(label: str, question: str, **kw) -> None:
        kw = {"metric": p.metric, "window": p.window, **kw}
        out.append(FollowUp(label=label, question=question, plan=AnalysisPlan(question=question, route="catalog", **kw)))

    decs = b.drivers.dimensions if b.drivers else []
    # the next-best dimension that splits into more than one segment (a South manager's region is South alone)
    nxt = next((d.dimension for d in decs[1:] if len(d.segments) > 1), None)
    if nxt and decs[0].segments and _drillable(decs[0].dimension, seg := decs[0].segments[0].segment):
        top = decs[0].dimension
        add(f"{seg} by {_dim(nxt)}",
            f"Why did {m} change for {_dim(top)} {seg}, by {_dim(nxt)}, {_in(win)}?",
            intent="explain_change", dimensions=[nxt], baseline=p.baseline,
            filters=[*p.filters, Filter(dimension=top, values=[seg])])
    region = next((d for d in decs if d.dimension == "region" and d.segments), None)
    if (region and decs[0].dimension != "region" and len(regions) > 1 and region.segments[0].segment in regions
            and not any(f.dimension == "region" for f in p.filters)):
        r = region.segments[0].segment
        add(f"Same question for {r}", f"Why did {m} change in the {r} region {_in(win)}?", intent="explain_change",
            dimensions=p.dimensions, baseline=p.baseline, filters=[*p.filters, Filter(dimension="region", values=[r])])
    n = (p.window.end - p.window.start).days + 1 if p.window.start and p.window.end else None
    if p.intent in ("metric_value", "breakdown", "trend"):
        if metric.type == "ratio":
            add("Explain the change", f"Why did {m} change {_in(win)}?", intent="explain_change", filters=p.filters)
        period = {1: "day", 7: "week"}.get(n or 0, f"{n} days" if n else "period")
        add(f"Compare with the {period} before", f"Compare {m} {_in(win)} with the {period} before",
            intent="compare_periods", dimensions=p.dimensions, filters=p.filters)
    elif p.intent in ("explain_change", "compare_periods") and p.baseline and p.baseline.start and p.window.end:
        # both periods, so the trend shows when the move began; hourly when they span two days or less
        start, end = p.baseline.start, p.window.end
        grain = "hour" if (end - start).days < 2 else "day"
        word = "Hourly" if grain == "hour" else "Daily"
        add(f"{word} trend", f"{word} {m}, {_range(start, end)}",
            intent="trend", grain=grain, filters=p.filters, window=TimeWindow(start=start, end=end))
    if b.dq and p.intent != "data_quality":
        add("Check data completeness", completeness_question(win), intent="data_quality", metric="attempts")
    # persona scope: never offer a region the persona cannot see (triage would refuse it anyway)
    out = [f for f in out if all(set(x.values) <= set(regions) for x in f.plan.filters if x.dimension == "region")]
    return out[:MAX_FOLLOW_UPS]


# ------------------------------------------------------------------ headline chips
_MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
# Numbers as contracts.format_value writes them. A count is never part of a date, time, range or id ("13 Nov",
# "13-19", "02:00", "E1", "last 7 days"), and format_value puts commas in every count over 999, so "2026" is a year.
_NUMBER = re.compile(
    r"(?<![\w.,])(?:"
    r"(?P<pp>[+-]?\d+(?:\.\d+)? pp\b)"
    r"|(?P<inr>[+-]?₹\d[\d,]*(?:\.\d+)?(?: (?:Cr|L)\b)?)"
    r"|(?P<pct>[+-]?\d+(?:\.\d+)?%)"
    rf"|(?P<int>(?<![:/-])(?<!{_MONTH} )[+-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?"
    rf"(?![\w:/%-])(?![.,]\d)(?! {_MONTH})(?! (?:days?|hours?|weeks?|months?)\b)))")


def headline_parts(headline: str | None, metric: str | None) -> list[HeadlinePart]:
    """The rendered headline cut into text and number chips; the parts join back to the headline exactly.
    ponytail: every signed delta is judged by the plan's metric; a headline quoting a second metric's delta would
    colour it by the first. Carry the metric per number if narration ever mixes them.
    ponytail: contracts.format_value signs a negative INR amount but never a positive one, so a GMV fall
    ('-₹2.50 L') is a coloured down chip while a rise ('₹3.53 Cr') reads as a plain value. Sign INR deltas where
    the evidence formats them (a contracts change, master only) to colour rises too."""
    if not headline:
        return []
    try:
        better = load_catalog().metric(metric).higher_is_better if metric else None
    except KeyError:
        better = None
    parts, at = [], 0
    for x in _NUMBER.finditer(headline):
        if x.start() > at:
            parts.append(HeadlinePart(text=headline[at:x.start()], kind="text", tone="neutral"))
        s = x.group()
        signed = s[0] in "+-" and any(c in "123456789" for c in s)
        kind = ("up" if s[0] == "+" else "down") if signed else "value"
        parts.append(HeadlinePart(text=s, kind=kind, tone=tone(kind, better) if better is not None else "neutral"))
        at = x.end()
    if at < len(headline):
        parts.append(HeadlinePart(text=headline[at:], kind="text", tone="neutral"))
    return parts


# ------------------------------------------------------------------ markdown
def _md(s: str) -> str:
    """Bundle text made inert in Markdown: no links, images, HTML or code spans when the copy is pasted."""
    return re.sub(r"([\\`\[\]<>])", r"\\\1", s)


def markdown(b: AnswerBundle) -> str:
    """The answer as Markdown: headline, confidence, the claims with their evidence ids, data quality, and a footer."""
    lines = [f"## {_md(b.headline or 'No headline was produced.')}", "", f"Question: {_md(b.question)}"]
    if b.confidence:   # one sentence per reason: they end in a full stop already, and some carry brackets
        why = " ".join(r if r.endswith(".") else f"{r}." for r in b.confidence_reasons)
        lines.append(f"Confidence: {b.confidence.capitalize()}." + (f" {_md(why)}" if why else ""))
    if b.route:
        lines.append("Source: " + ("governed metric" if b.route == "catalog" else "model-written SQL (unverified)"))
    if b.claims:
        lines.append("")
        for n, c in enumerate(b.claims, 1):
            ids = list(dict.fromkeys(c.evidence_ids))
            lines.append(f"{n}. **{c.kind.capitalize()}.** {_md(c.rendered)}" + (f" [{', '.join(ids)}]" if ids else ""))
    if b.dq:
        lines += ["", "Data quality:"]
        lines += [f"- {w.check.replace('_', ' ').capitalize()} ({w.severity}): {_md(w.message)}" for w in b.dq]
    foot = [f"Run {b.run_id}", b.data_version and f"data {b.data_version}", b.as_of and f"as of {b.as_of:%d %b %Y}"]
    lines += ["", "---", " · ".join(x for x in foot if x) + " · Sherpa"]
    return "\n".join(lines) + "\n"
