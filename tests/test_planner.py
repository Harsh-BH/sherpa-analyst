import json
from datetime import date

import anthropic
import pytest

from sherpa import llm, planner
from sherpa.config import load_catalog
from sherpa.contracts import AnalysisPlan
from sherpa.triage import triage

AS_OF, START = date(2026, 11, 19), date(2026, 9, 21)   # as_of is a Thursday


def test_preset_dates():
    d = {k: (s.isoformat(), e.isoformat()) for k, (s, e) in planner.preset_dates(AS_OF, START).items()}
    assert d["yesterday"] == ("2026-11-19", "2026-11-19")
    assert d["last_7_days"] == ("2026-11-13", "2026-11-19")
    assert d["previous_7_days"] == ("2026-11-06", "2026-11-12")
    assert d["last_30_days"] == ("2026-10-21", "2026-11-19")
    assert d["month_to_date"] == ("2026-11-01", "2026-11-19")
    assert d["last_month"] == ("2026-10-01", "2026-10-31")
    assert d["last_calendar_week"] == ("2026-11-09", "2026-11-15")
    assert d["all_data"] == ("2026-09-21", "2026-11-19")
    # a Sunday as_of closes its own week; early as_of clamps to data_start
    assert planner.preset_dates(date(2026, 11, 15), START)["last_calendar_week"][1] == date(2026, 11, 15)
    assert planner.preset_dates(date(2026, 10, 1), START)["last_month"][0] == START


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_schema_is_strict_and_catalog_constrained():
    s = planner.plan_schema()
    cat = load_catalog()
    for node in _walk(s):
        assert "default" not in node and "title" not in node
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
    assert s["properties"]["metric"]["anyOf"][0]["enum"] == [m.name for m in cat.metrics]
    assert s["properties"]["dimensions"]["items"]["enum"] == [d.name for d in cat.dimensions]
    assert s["$defs"]["Filter"]["properties"]["dimension"]["enum"] == [d.name for d in cat.dimensions]
    assert "label" not in s["$defs"]["TimeWindow"]["properties"]
    assert "last_calendar_week" in json.dumps(s["$defs"]["TimeWindow"])
    anthropic.transform_schema(s)          # the SDK accepts it
    json.dumps(s)


def test_system_prompt_is_static_and_complete():
    sp = planner.system_prompt()
    cat = load_catalog()
    for name in [*(m.name for m in cat.metrics), *(d.name for d in cat.dimensions), *planner.PRESET_MEANING]:
        assert f"`{name}`" in sp
    for vq in cat.verified_queries:
        assert vq.question in sp
    assert "display_name" in sp and "refuse" in sp and "denominator" in sp
    # nothing per-request leaks in: no persona scope line, no resolved preset dates
    assert "Visible regions" not in sp and "Window presets resolve" not in sp


def test_user_message():
    um = planner.user_message("Why did SR drop?", "rm_south", AS_OF, START)
    assert "Regional manager, South" in um and "Visible regions: South." in um
    assert "2026-11-19" in um and "2026-09-21" in um
    assert "- previous_7_days: 2026-11-06 .. 2026-11-12" in um
    assert um.endswith("Question: Why did SR drop?")


def test_examples_are_valid_and_triage_as_intended():
    """Every few-shot plan must itself be a plan triage accepts (or refuses/clarifies on purpose)."""
    cat = load_catalog()
    for vq in cat.verified_queries:
        p = AnalysisPlan.model_validate(planner._example_plan(vq.question, vq.plan))
        assert triage(p, "head").action == "proceed", vq.name
    want = {"refuse": "refuse", "sql": "proceed", "clarify": "clarify", "catalog": "proceed"}
    for who, q, raw in planner._EXTRA_EXAMPLES:
        p = AnalysisPlan.model_validate(planner._example_plan(q, raw))
        r = triage(p, who)
        assert r.action == want[p.route], q
        if who == "rm_south":
            assert r.refusal.plan_patch is not None      # scope refusal comes with an offer


def fake_structured(answer):
    seen = {}

    def structured(**kw):
        seen.update(kw)
        return dict(answer), {"backend": "fake", "cost_usd": 0.0}
    return structured, seen


def test_plan_validates_and_adds_denominator_ambiguity(monkeypatch):
    out = {"question": "paraphrased", "route": "catalog", "intent": "explain_change", "metric": "success_rate",
           "dimensions": [], "filters": [], "window": {"preset": "last_7_days", "start": None, "end": None},
           "baseline": {"preset": "previous_7_days", "start": None, "end": None}, "grain": "day", "sql": None,
           "assumptions": ["'last week' read as the last 7 complete days"], "ambiguities": [],
           "refuse_reason": None, "clarify_question": None}
    structured, seen = fake_structured(out)
    monkeypatch.setattr(llm, "structured", structured)
    p, usage = planner.plan("Why did success rate drop last week?", "head", as_of=AS_OF, data_start=START)
    assert p.question == "Why did success rate drop last week?"
    assert p.ambiguities[0].kind == "denominator"
    assert p.ambiguities[0].options == ["success_rate", "success_rate_incl_dropoffs"]
    assert seen["system"] == planner.system_prompt() and seen["schema"] == planner.plan_schema()
    assert usage["backend"] == "fake"
    # the pinned reading gets no ambiguity
    p, _ = planner.plan("Why did success rate excluding drop-offs fall?", "head", as_of=AS_OF, data_start=START)
    assert p.ambiguities == []


def test_plan_invalid_output_raises(monkeypatch):
    monkeypatch.setattr(llm, "structured", fake_structured({"route": "catalog", "intent": "teleport"})[0])
    with pytest.raises(llm.LLMUnavailable, match="invalid plan"):
        planner.plan("q", "head", as_of=AS_OF, data_start=START)


@pytest.mark.live
def test_live_planner_explain_change():
    p, usage = planner.plan("Why did success rate drop last week?", "head", as_of=AS_OF, data_start=START)
    print("\nLIVE planner explain_change:", p.model_dump_json(exclude_defaults=True), usage)
    assert p.route == "catalog" and p.intent == "explain_change" and p.metric == "success_rate"
    assert p.window.preset == "last_7_days" and p.baseline.preset == "previous_7_days"
    assert any(a.kind == "denominator" for a in p.ambiguities) and p.assumptions
    assert triage(p, "head").action == "proceed"


@pytest.mark.live
def test_live_planner_out_of_scope():
    p, usage = planner.plan("Compare North vs South success rate", "rm_south", as_of=AS_OF, data_start=START)
    r = triage(p, "rm_south")
    print("\nLIVE planner out-of-scope:", p.model_dump_json(exclude_defaults=True), usage,
          "\n  triage:", r.action, r.refusal)
    assert r.action == "refuse" and "North" in r.refusal.reason
