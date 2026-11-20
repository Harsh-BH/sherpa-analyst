"""The Streamlit app in fixture mode: every fixture and every mode renders, evidence is visible, data stays inert."""
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import backend
from app.render import esc
from sherpa.contracts import AnalysisPlan

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")
INJECTION = backend.load_fixture("sql_route").evidence[0].table[1]["display_name"]


@pytest.fixture(autouse=True)
def fixture_mode(monkeypatch):
    monkeypatch.setenv("SHERPA_UI_FIXTURES", "1")


def app(**state) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def ask(question: str, persona: str = "head") -> AppTest:
    at = app(persona=persona)
    at.text_input(key="question").input(question).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def assert_inert(at: AppTest):
    """Nothing opted into raw HTML, and no element body carries an unescaped injection payload."""
    bodies = [m.value for m in at.markdown] + [e.value for kind in ("error", "warning", "info") for e in at.get(kind)]
    assert not any(getattr(m, "allow_html", False) or m.proto.allow_html for m in at.markdown)
    assert not any(INJECTION in b or "<img" in b for b in bodies)


# ------------------------------------------------------------------ pure helpers
@pytest.mark.parametrize("question,persona,expected", [
    ("Why did success rate drop last week?", "head", "explain_change"),
    ("Card success rate fell on <S3 date>: what drove it?", "head", "explain_change"),
    ("Why doesn't settled amount match GMV for <S4 date>?", "head", "reconcile"),
    ("What was the success rate yesterday?", "head", "clarify"),
    ("Which merchants had the most failed payments last week?", "head", "sql_route"),
    ("Compare North vs South success rate", "rm_south", "refused"),
    ("Compare North vs South success rate", "head", "explain_change"),   # head may see North: nothing to refuse
    ("Is last week's data complete?", "head", "explain_change"),         # no match: the showcase bundle
])
def test_fixture_matching(question, persona, expected):
    assert backend.fixture_name(question, persona) == expected


def test_a_plan_handed_back_is_never_re_asked_or_refused():
    plan = AnalysisPlan(question="q", route="catalog", intent="metric_value", metric="success_rate")
    assert backend.fixture_name("What was the success rate yesterday?", "head", plan) != "clarify"
    assert backend.fixture_name("Compare North vs South success rate", "rm_south", plan) != "refused"


def test_patched_resolves_the_plan():
    c = backend.load_fixture("clarify")
    p = backend.patched(c.plan, c.clarification.options[1].plan_patch)
    assert p.metric == "success_rate_incl_dropoffs" and p.ambiguities == [] and p.route == "catalog"
    r = backend.load_fixture("refused")
    p = backend.patched(r.plan, r.refusal.plan_patch)
    assert p.route == "catalog" and p.refuse_reason is None and p.filters[0].values == ["South"]


def test_esc_neutralises_markdown_html_and_directives():
    for s in (INJECTION, ":red[x] :material/home: $x^2$ <b>hi</b> ![i](http://e/x.png) www.evil.com"):
        out = esc(s)
        assert not re.search(r"(?<!\\)[<>\[\]()$:!]", out), out
        assert re.sub(r"\\(.)", r"\1", out) == s          # unescaping gives the original text back


# ------------------------------------------------------------------ pages
def test_explain_change_shows_tags_sql_charts_and_dq():
    at = ask("Why did success rate drop last week?")
    md = markdown(at)
    for tag in ("Fact", "Hypothesis", "Recommendation", "Caveat"):
        assert re.search(rf":\w+-badge\[[^\]]*{tag}\]", md), tag
    assert [c for c in at.code if c.language == "sql"], "SQL code blocks"
    assert any("PG" in w.value and "Data quality" in w.value for w in at.warning), "DQ banner"
    assert "Simpson" in "\n".join(i.value for i in at.info)
    assert len(at.get("vega_lite_chart")) >= 4                    # waterfall + one per evidence
    assert at.get("download_button")
    assert "v1 · seed 42" in md and "19 Nov 2026" in md                 # sidebar data version and as_of
    assert_inert(at)


def test_sql_route_is_labelled_and_injection_stays_text():
    at = ask("Which merchants had the most failed payments last week?")
    assert "Unverified SQL" in markdown(at) and any("Unverified SQL" in w.value for w in at.warning)
    cells = [v for df in at.dataframe for v in df.value.astype(str).to_numpy().ravel()]
    assert INJECTION in cells                                            # shown verbatim, as a table cell
    assert_inert(at)


def test_clarification_options_show_previews_and_answer():
    at = ask("What was the success rate yesterday?")
    labels = [b.label for b in at.button if b.key and b.key.startswith("clarify-")]
    assert len(labels) == 2 and all("%" in lab for lab in labels)
    next(b for b in at.button if b.key and b.key.startswith("clarify-")).click().run()
    assert not at.exception and at.session_state["bundle"].status == "answered"


def test_refusal_card_and_suggested_plan():
    at = ask("Compare North vs South success rate", persona="rm_south")
    assert any("out of scope" in e.value for e in at.error)
    at.button(key="refusal-fx-refused-0001").click().run()
    assert not at.exception and at.session_state["bundle"].status == "answered"


def test_reconcile_renders_bridge():
    at = ask("Why doesn't settled amount match GMV for the last 7 days?")
    assert "Reconciliation components" in markdown(at) and at.get("vega_lite_chart")


def test_partial_pipeline_data_does_not_crash_the_card():
    b = backend.load_fixture("explain_change")
    b.evidence[0].values["note"] = "free text, no format"     # a string value with no ValueFormat
    b.claims[0].evidence_ids = ["E1", "E1", "E9"]               # duplicate and dangling evidence ids
    b.llm_usage = {"backend": "template", "cost_usd": None}
    at = app(bundle=b)
    assert not at.exception, [e.value for e in at.exception]
    assert any("No evidence E9" in w.value for w in at.warning)


def test_error_card_keeps_run_id():
    at = app(bundle=backend.load_fixture("error"))
    assert not at.exception and any("failed" in e.value for e in at.error)
    assert any(c.value == "fx-error-0001" for c in at.code)


def test_demo_chip_switches_persona():
    at = app()
    at.pills[0].set_value("Compare North vs South success rate").run()
    assert not at.exception
    assert at.session_state["persona"] == "rm_south" and at.session_state["bundle"].status == "refused"


def test_deep_link_ignores_unknown_persona():
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["q"] = "Why did success rate drop last week?"
    at.query_params["persona"] = "superuser"
    at.run()
    assert not at.exception and at.session_state["persona"] == "head"
    assert at.session_state["bundle"].status == "answered"


@pytest.mark.parametrize("mode", ["Ask", "Explore", "Eval", "Runs"])
def test_every_mode_renders(mode):
    at = app()
    at.sidebar.radio(key="mode").set_value(mode).run()
    assert not at.exception, [e.value for e in at.exception]
    if mode == "Eval":
        assert len(at.metric) == 7 and at.dataframe
    if mode == "Runs":
        assert at.metric or at.info                    # live stats, or a clear "unavailable" message


def test_explore_builds_a_catalog_plan_and_runs_it():
    at = app(mode="Explore")
    at.multiselect(key="x_dims").set_value(["payment_method"])
    at.multiselect(key="x_filter_dims").set_value(["region"]).run()
    at.multiselect(key="x_f_region").set_value(["South"]).run()
    next(b for b in at.button if b.label == "Run plan").click().run()
    assert not at.exception and at.session_state["bundle"].status == "answered"
    shown = at.get("json")[0].value
    assert '"route": "catalog"' in shown and '"payment_method"' in shown and '"South"' in shown
