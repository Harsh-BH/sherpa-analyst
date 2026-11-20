import pytest

from sherpa.contracts import AnalysisPlan, Ambiguity
from sherpa.triage import triage


def P(**kw):
    base = {"question": "q", "route": "catalog", "intent": "metric_value", "metric": "success_rate",
            "window": {"preset": "last_7_days"}}
    return AnalysisPlan.model_validate({**base, **kw})


def apply(plan, option):
    return AnalysisPlan.model_validate({**plan.model_dump(), **option.plan_patch})


def test_proceed_and_canonical_names():
    r = triage(P(metric="SR", dimensions=["bank", "issuer_bank_id", "payment mode"]), "head")
    assert r.action == "proceed"
    assert r.plan.metric == "success_rate"
    assert r.plan.dimensions == ["issuer_bank", "payment_method"]
    assert r.variant_metrics == [] and r.clarification is None and r.refusal is None


@pytest.mark.parametrize("dim,raw,want", [
    ("payment_method", "upi", "UPI"), ("method", "cards", "CARD"), ("payment_method", "Net Banking", "NETBANKING"),
    ("bank", "Kestrel Bank", "KESTREL"), ("issuer_bank", "heron", "HERON"), ("gateway", "pg a", "PG_A"),
    ("txn_hour", "09", "9"), ("region", "south", "South"), ("device", "iOS", "ios"), ("merchant", " M00042 ", "M00042"),
    ("txn_date", "2026-11-14", "2026-11-14"),
])
def test_filter_values_normalised(dim, raw, want):
    r = triage(P(filters=[{"dimension": dim, "values": [raw]}]), "head")
    assert r.action == "proceed", r.clarification
    assert r.plan.filters[0].values == [want]


def test_unknown_metric_clarifies_with_close_match():
    plan = P(metric="sucess rate")
    r = triage(plan, "head")
    assert r.action == "clarify"
    assert r.clarification.options[0].plan_patch == {"metric": "success_rate"}
    assert triage(apply(plan, r.clarification.options[0]), "head").action == "proceed"


def test_missing_metric():
    assert triage(P(metric=None, intent="reconcile"), "head").plan.metric == "settled_net"
    r = triage(P(metric=None, intent="breakdown"), "head")
    assert r.action == "clarify" and {"metric": "success_rate"} in [o.plan_patch for o in r.clarification.options]


def test_unknown_dimension_clarifies():
    plan = P(dimensions=["payment_method", "netwrk"])
    r = triage(plan, "head")
    assert r.action == "clarify"
    labels = [o.label for o in r.clarification.options]
    assert "Card network" in labels and "Without 'netwrk'" in labels
    for o in r.clarification.options:
        assert triage(apply(plan, o), "head").action == "proceed"


def test_unknown_filter_dimension_clarifies():
    plan = P(filters=[{"dimension": "gatway", "values": ["PG_A"]}])
    r = triage(plan, "head")
    assert r.action == "clarify" and r.clarification.options[0].label == "Gateway"
    assert all(triage(apply(plan, o), "head").action == "proceed" for o in r.clarification.options)


def test_unknown_filter_value_clarifies():
    plan = P(filters=[{"dimension": "issuer_bank", "values": ["KESTREL", "HERONN"]}])
    r = triage(plan, "head")
    assert r.action == "clarify"
    assert r.clarification.options[0].label == "HERON"
    fixed = triage(apply(plan, r.clarification.options[0]), "head")
    assert fixed.action == "proceed" and fixed.plan.filters[0].values == ["KESTREL", "HERON"]
    ignored = triage(apply(plan, r.clarification.options[-1]), "head")
    assert ignored.plan.filters[0].values == ["KESTREL"]


def test_bad_typed_values_clarify():
    assert triage(P(filters=[{"dimension": "txn_hour", "values": ["noon"]}]), "head").action == "clarify"
    assert triage(P(filters=[{"dimension": "txn_date", "values": ["last tuesday"]}]), "head").action == "clarify"


def test_dimension_not_on_metric_table():
    plan = P(metric="settled_net", dimensions=["payment_method", "region"])
    r = triage(plan, "head")
    assert r.action == "clarify"
    fixed = triage(apply(plan, r.clarification.options[0]), "head")
    assert fixed.action == "proceed" and fixed.plan.dimensions == ["region"]
    plan = P(metric="refunds", filters=[{"dimension": "gateway", "values": ["PG_A"]}])
    assert triage(plan, "head").action == "clarify"


def test_out_of_scope_region_filter_refused_with_offer():
    plan = P(question="Compare North vs South success rate", intent="breakdown", dimensions=["region"],
             filters=[{"dimension": "region", "values": ["north", "South"]}])
    r = triage(plan, "rm_south")
    assert r.action == "refuse"
    assert "North" in r.refusal.reason and "South" in r.refusal.reason and "Regional manager" in r.refusal.reason
    assert r.refusal.suggestion and "South" in r.refusal.suggestion
    offer = triage(apply(plan, r.clarification.options[0]), "rm_south")
    assert offer.action == "proceed"
    assert offer.plan.filters[0].values == ["South"]
    # head sees everything
    assert triage(plan, "head").action == "proceed"


def test_out_of_scope_region_in_question_only():
    plan = P(question="What's the success rate in the North?")
    r = triage(plan, "rm_south")
    assert r.action == "refuse" and r.clarification is not None
    assert triage(apply(plan, r.clarification.options[0]), "rm_south").action == "proceed"
    # scope beats a planner refusal or clarification: the refusal still carries the offer
    assert triage(P(question="North SR?", route="refuse", refuse_reason="North is out of scope"), "rm_south").clarification
    assert triage(P(question="North SR?", route="clarify"), "rm_south").action == "refuse"


def test_in_scope_and_exclusions_proceed():
    r = triage(P(question="South success rate"), "rm_south")
    assert r.action == "proceed" and any("South only" in a for a in r.plan.assumptions)
    assert triage(P(filters=[{"dimension": "region", "op": "not_in", "values": ["North"]}]), "rm_south").action == "proceed"
    # 'southern', 'northeast-ish' words are not region names
    assert triage(P(question="Is the southern trend worse than at least last week?"), "rm_south").action == "proceed"


def test_planner_refusal_for_other_reason_gets_no_scope_offer():
    r = triage(P(question="Forecast North GMV for December", route="refuse",
                 refuse_reason="Forecasts are not supported."), "rm_south")
    assert r.action == "refuse" and r.clarification is None
    assert "Forecasts" in r.refusal.reason and "North" in r.refusal.reason
    r = triage(P(question="Compare North vs South", route="refuse",
                 refuse_reason="North is outside the South-only scope."), "rm_south")
    assert r.clarification is not None


def test_sql_route_out_of_scope_has_no_patch():
    r = triage(P(route="sql", sql="SELECT 1", question="North merchants with most refunds"), "rm_south")
    assert r.action == "refuse" and r.clarification is None


def test_default_windows():
    r = triage(P(window=None), "head")
    assert r.plan.window.preset == "last_7_days" and "last 7 days" in r.plan.assumptions[0]
    r = triage(P(intent="explain_change"), "head")
    assert r.plan.baseline.preset == "previous_7_days" and any("previous 7 days" in a for a in r.plan.assumptions)
    r = triage(P(intent="compare_periods", window={"preset": "last_14_days"}), "head")
    assert r.plan.baseline is None and any("preceding period" in a for a in r.plan.assumptions)
    r = triage(P(intent="explain_change", window=None), "head")
    assert r.plan.baseline.preset == "previous_7_days" and len(r.plan.assumptions) == 2
    r = triage(P(intent="compare_periods", baseline={"preset": "last_month"}), "head")
    assert r.plan.baseline.preset == "last_month" and r.plan.assumptions == []
    r = triage(P(window={"start": "2026-11-01", "end": "2026-11-07"}), "head")
    assert r.plan.window.start.isoformat() == "2026-11-01" and r.plan.assumptions == []


def test_variant_metrics_from_denominator_ambiguity():
    amb = Ambiguity(kind="denominator", description="d", options=["success_rate", "success_rate_incl_dropoffs"])
    r = triage(P(ambiguities=[amb.model_dump()]), "head")
    assert r.action == "proceed" and r.variant_metrics == ["success_rate_incl_dropoffs"]
    # options that are not catalog variants of the chosen metric are ignored
    amb = Ambiguity(kind="denominator", description="d", options=["gmv"])
    assert triage(P(ambiguities=[amb.model_dump()]), "head").variant_metrics == []


def test_sql_route():
    assert triage(P(route="sql", sql=None), "head").action == "clarify"
    r = triage(P(route="sql", sql="SELECT count(*) FROM analytics.transactions", metric=None), "head")
    assert r.action == "proceed"


def test_planner_refuse_and_clarify_pass_through():
    r = triage(P(route="refuse", refuse_reason="Forecasts are not supported."), "head")
    assert r.action == "refuse" and r.refusal.reason == "Forecasts are not supported."
    amb = Ambiguity(kind="metric", description="which", options=["success_rate", "success_rate_incl_dropoffs", "foo"])
    tw = Ambiguity(kind="time_window", description="when", options=["last_month"])
    plan = P(route="clarify", clarify_question="Which success rate?", ambiguities=[amb.model_dump(), tw.model_dump()])
    r = triage(plan, "head")
    assert r.action == "clarify" and r.clarification.question == "Which success rate?"
    assert [o.plan_patch for o in r.clarification.options] == [
        {"metric": "success_rate", "route": "catalog"}, {"metric": "success_rate_incl_dropoffs", "route": "catalog"},
        {"window": {"preset": "last_month"}, "route": "catalog"}]
    assert triage(apply(plan, r.clarification.options[0]), "head").action == "proceed"


def test_input_plan_not_mutated():
    plan = P(metric="SR", window=None)
    triage(plan, "head")
    assert plan.metric == "SR" and plan.window is None
