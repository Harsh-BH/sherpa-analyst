"""Question -> AnalysisPlan. The only LLM job here is translation; triage checks the result deterministically.

The system prompt is built from the catalog and access files only, so it is identical for every persona and
question and caches; everything that varies (question, persona, dates) goes in the user message.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from . import llm
from .config import load_access, load_catalog, persona as get_persona, settings
from .contracts import Ambiguity, AnalysisPlan, Catalog

PROMPT = Path(__file__).parent / "prompts" / "planner.md"

PRESET_MEANING = {
    "yesterday": "the latest complete day (as_of)",
    "last_7_days": "as_of-6 .. as_of; also 'last week', 'this week', 'past week'",
    "previous_7_days": "as_of-13 .. as_of-7; the baseline for last_7_days ('the week before')",
    "last_14_days": "as_of-13 .. as_of; 'last two weeks', 'past fortnight'",
    "last_28_days": "as_of-27 .. as_of; 'last four weeks'",
    "last_30_days": "as_of-29 .. as_of; 'last month' when it means a rolling month, 'past 30 days'",
    "month_to_date": "1st of as_of's month .. as_of; 'this month', 'MTD'",
    "last_month": "the previous calendar month; 'last month' when it means the calendar month, 'in October'",
    "last_calendar_week": "Monday..Sunday of the last complete calendar week",
    "all_data": "data_start .. as_of; 'all time', 'since we have data'",
}

# Words that pin which success-rate denominator the user means (so no denominator ambiguity is raised).
# ponytail: keyword list, the LLM is also told the rule; move to catalog synonyms if it grows
_PINNED = ("drop-off", "dropoff", "drop off", "abandon", "incl", "excl", "conversion", "end-to-end", "end to end",
           "reached the bank", "all attempts", "of attempts", "checkout")


def preset_dates(as_of: date, data_start: date) -> dict[str, tuple[date, date]]:
    """What each preset means today, clamped to the data range (mirrors compiler.resolve_window)."""
    d = timedelta
    first = as_of.replace(day=1)
    lm_end = first - d(days=1)
    week_end = as_of - d(days=(as_of.weekday() + 1) % 7)       # last Sunday on or before as_of
    raw = {
        "yesterday": (as_of, as_of),
        "last_7_days": (as_of - d(days=6), as_of),
        "previous_7_days": (as_of - d(days=13), as_of - d(days=7)),
        "last_14_days": (as_of - d(days=13), as_of),
        "last_28_days": (as_of - d(days=27), as_of),
        "last_30_days": (as_of - d(days=29), as_of),
        "month_to_date": (first, as_of),
        "last_month": (lm_end.replace(day=1), lm_end),
        "last_calendar_week": (week_end - d(days=6), week_end),
        "all_data": (data_start, as_of),
    }
    return {k: (max(s, data_start), e) for k, (s, e) in raw.items()}


def _clean(node):
    """Pydantic JSON schema -> strict structured-output schema: no titles/defaults, closed objects, all keys required."""
    if isinstance(node, list):
        return [_clean(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _clean(v) for k, v in node.items() if k not in ("title", "default")}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


@lru_cache(maxsize=1)
def plan_schema() -> dict:
    cat = load_catalog()
    s = AnalysisPlan.model_json_schema()
    metrics = [m.name for m in cat.metrics]
    dims = [d.name for d in cat.dimensions]
    p = s["properties"]
    p["metric"] = {"anyOf": [{"type": "string", "enum": metrics}, {"type": "null"}],
                   "description": "catalog metric name; null only for the sql route"}
    p["dimensions"] = {"type": "array", "items": {"type": "string", "enum": dims},
                       "description": "group-by dimensions; for explain_change, candidate drivers ([] = all)"}
    p["sql"]["description"] = "sql route only: one Postgres SELECT over analytics.*"
    s["$defs"]["Filter"]["properties"]["dimension"] = {"type": "string", "enum": dims}
    del s["$defs"]["TimeWindow"]["properties"]["label"]    # filled by the resolver, never by the model
    return _clean(s)


def _example_plan(question: str, plan: dict) -> dict:
    p = _with_denominator_ambiguity(AnalysisPlan.model_validate({"question": question, **plan}))
    out = p.model_dump(mode="json")
    for w in ("window", "baseline"):
        if out[w]:
            out[w].pop("label", None)
    return out


# Hand-written examples for the routes the verified queries do not cover. (persona, question, plan)
_EXTRA_EXAMPLES = [
    ("head", "Forecast our GMV for December",
     {"route": "refuse", "intent": "metric_value", "metric": "gmv",
      "refuse_reason": "Forecasts are not supported: Sherpa reports what the data shows, not predictions."}),
    ("head", "List the card numbers and customer names that failed yesterday",
     {"route": "refuse", "intent": "breakdown", "metric": "attempts", "window": {"preset": "yesterday"},
      "refuse_reason": "Card numbers and customer names are personal data and are not available."}),
    ("rm_south", "Compare North vs South success rate last week",
     {"route": "refuse", "intent": "breakdown", "metric": "success_rate", "dimensions": ["region"],
      "filters": [{"dimension": "region", "op": "in", "values": ["North", "South"]}],
      "window": {"preset": "last_7_days"},
      "assumptions": ["'last week' read as the last 7 complete days"],
      "refuse_reason": "North is outside this persona's access (South only)."}),
    ("head", "What share of UPI attempts in the last 7 days were retries?",
     {"route": "sql", "intent": "metric_value", "window": {"preset": "last_7_days"},
      "sql": "SELECT avg(CASE WHEN attempt_no > 1 THEN 1.0 ELSE 0.0 END) AS retry_share, count(*) AS attempts\n"
             "FROM analytics.transactions\n"
             "WHERE payment_method = 'UPI' AND txn_date BETWEEN DATE '2026-11-13' AND DATE '2026-11-19'",
      "assumptions": ["A retry is an attempt with attempt_no greater than 1."]}),
    ("head", "How did the bank do yesterday?",
     {"route": "clarify", "intent": "metric_value", "metric": "success_rate", "window": {"preset": "yesterday"},
      "clarify_question": "Which bank do you mean?",
      "ambiguities": [{"kind": "dimension_value", "description": "The question does not name a bank.",
                       "options": ["KESTREL", "HERON", "OSPREY", "MYNA", "EGRET", "IBIS", "HORNBILL", "BULBUL",
                                   "SARUS", "DRONGO"]}]}),
    ("head", "Success rate excluding drop-offs on PG_B by hour, 14 Nov",
     {"route": "catalog", "intent": "trend", "metric": "success_rate", "grain": "hour",
      "filters": [{"dimension": "gateway", "op": "in", "values": ["PG_B"]}],
      "window": {"start": "2026-11-14", "end": "2026-11-14"},
      "assumptions": ["'14 Nov' read as 14 Nov 2026 (IST)."]}),
]


def _catalog_text(cat: Catalog) -> str:
    acc = load_access()
    lines = ["# Tables", ""]
    for name, t in cat.tables.items():
        lines.append(f"- `{name}` ({t.sql_table}, time column {t.time_column}): {t.description}")
    lines += ["", "# Metrics", ""]
    for m in cat.metrics:
        lines.append(f"- `{m.name}` ({m.label}; {m.type}, {m.format}, table {m.table}"
                     f"{', by ' + m.time_column if m.time_column else ''}"
                     f"{', lower is better' if not m.higher_is_better else ''}): {m.description}")
        if m.synonyms:
            lines.append(f"  synonyms: {', '.join(m.synonyms)}")
        if m.variants:
            lines.append(f"  variants (other readings of the same loose question): {', '.join(m.variants)}")
    lines += ["", "# Dimensions", ""]
    for d in cat.dimensions:
        vals = ", ".join(d.values) if d.values and d.name != "txn_hour" else (
            "0..23" if d.name == "txn_hour" else "open (ids or ISO dates)")
        lines.append(f"- `{d.name}` ({d.label}; column {d.column}; tables {', '.join(d.tables)}"
                     f"{'; not a driver candidate' if not d.driver else ''}): values {vals}")
        if d.synonyms:
            lines.append(f"  synonyms: {', '.join(d.synonyms)}")
    lines += ["", "# Window presets", ""]
    lines += [f"- `{k}`: {v}" for k, v in PRESET_MEANING.items()]
    lines += ["", "# SQL route: readable tables and columns (schema analytics)", ""]
    lines += [f"- analytics.{t}: {', '.join(cols)}" for t, cols in acc.exposed_tables.items()]
    lines += ["", "# Examples", "",
              "Verified question -> plan pairs. Dates in them are illustrative; use today's preset dates."]
    for vq in cat.verified_queries:
        lines += ["", f"Persona: head. Question: {vq.question}",
                  json.dumps(_example_plan(vq.question, vq.plan), separators=(",", ":"))]
    for who, q, p in _EXTRA_EXAMPLES:
        lines += ["", f"Persona: {who}. Question: {q}", json.dumps(_example_plan(q, p), separators=(",", ":"))]
    return "\n".join(lines)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return PROMPT.read_text().strip() + "\n\n" + _catalog_text(load_catalog())


def user_message(question: str, persona: str, as_of: date, data_start: date) -> str:
    p = get_persona(persona)
    lines = [f"Persona: {p.label} (id {p.name}). Visible regions: {', '.join(p.regions)}.",
             f"Data available from {data_start.isoformat()} (data_start) to {as_of.isoformat()} (as_of, the latest "
             f"complete day, IST). Today is {(as_of + timedelta(days=1)).strftime('%a %d %b %Y')}.",
             "Window presets resolve to (inclusive):"]
    for k, (s, e) in preset_dates(as_of, data_start).items():
        lines.append(f"- {k}: {s.isoformat()} .. {e.isoformat()} ({s.strftime('%a %d %b')} - {e.strftime('%a %d %b %Y')})")
    lines += ["", f"Question: {question}"]
    return "\n".join(lines)


def _with_denominator_ambiguity(plan: AnalysisPlan) -> AnalysisPlan:
    """Deterministic backstop for the denominator rule: an unpinned metric with variants gets the ambiguity."""
    if plan.metric is None or any(a.kind == "denominator" for a in plan.ambiguities):
        return plan
    try:
        m = load_catalog().metric(plan.metric)
    except KeyError:
        return plan
    if not m.variants or any(w in plan.question.lower() for w in _PINNED):
        return plan
    amb = Ambiguity(kind="denominator", options=[m.name, *m.variants],
                    description=f"'{m.label}' can be computed over payments that reached the bank or over all "
                                f"attempts; using {m.label.lower()}.")
    return plan.model_copy(update={"ambiguities": [*plan.ambiguities, amb]})


def plan(question: str, persona: str, *, as_of: date, data_start: date) -> tuple[AnalysisPlan, dict]:
    data, usage = llm.structured(system=system_prompt(), user=user_message(question, persona, as_of, data_start),
                                 schema=plan_schema(), model=settings().planner_model, max_tokens=16000)
    data["question"] = question          # the model must not paraphrase what it was asked
    try:
        p = AnalysisPlan.model_validate(data)
    except ValidationError as e:
        raise llm.LLMUnavailable(f"planner returned an invalid plan: {e}"[:800]) from e
    return _with_denominator_ambiguity(p), usage
