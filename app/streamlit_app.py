"""Sherpa UI: Ask | Explore | Eval | Runs.

    uv run streamlit run app/streamlit_app.py            (SHERPA_UI_FIXTURES=1 for offline demo data)

Calls only sherpa.pipeline.answer (through app.backend), sherpa.config loaders, sherpa.runs and
eval/results/latest.json. Data-derived text is rendered inert (see app/render.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # `streamlit run` puts app/ on sys.path, not the repo root
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import backend, render  # noqa: E402
from app.render import esc  # noqa: E402
from sherpa.config import load_access, load_catalog, settings  # noqa: E402
from sherpa.contracts import AnalysisPlan, Filter, Intent, TimeWindow, WindowPreset  # noqa: E402

# The five demo questions. ponytail: scenario dates are placeholders until I3 reads them from the ground truth.
S2_DATE, S3_DATE, S4_DATE = "<S2 date>", "<S3 date>", "<S4 date>"
DEMO = {
    "Why did success rate drop last week?": None,
    f"Why did success rate fall on {S2_DATE}?": None,
    f"Card success rate fell on {S3_DATE}: what drove it?": None,
    f"Why doesn't settled amount match GMV for {S4_DATE}?": None,
    "Compare North vs South success rate": "rm_south",   # asked as rm_south: shows the explained refusal
}

st.set_page_config(page_title="Sherpa", page_icon=":material/insights:", layout="wide")
access, catalog = load_access(), load_catalog()
pipe, fixture_reason = backend.pipeline_status()


def submit(question: str, persona: str, plan: AnalysisPlan | None = None) -> None:
    """Queue a run; the page body runs it under a spinner (callbacks run before the page renders)."""
    st.session_state.pending = (question, persona, plan)


def ask_typed() -> None:
    q = st.session_state.get("question", "").strip()
    if q:
        submit(q, st.session_state.persona)


def ask_chip(key: str) -> None:
    q = st.session_state.get(key)
    if not q:
        return
    if DEMO.get(q):
        st.session_state.persona = DEMO[q]
    st.session_state.question = q
    st.session_state[key] = None          # a chip is a button, not a sticky selection
    submit(q, st.session_state.persona)


# Deep link: ?q=<question>[&persona=<name>] asks once on first load (demo links, headless screenshots).
if "q" in st.query_params and "deep_link_done" not in st.session_state:
    st.session_state.deep_link_done = True
    if st.query_params.get("persona") in access.personas:
        st.session_state.persona = st.query_params["persona"]
    st.session_state.question = st.query_params["q"][:500]
    submit(st.session_state.question, st.session_state.get("persona", next(iter(access.personas))))

# Run a queued question before anything renders, so the sidebar already shows its data version.
if pending := st.session_state.pop("pending", None):
    with st.spinner("Planning, running governed queries, checking every number…"):
        st.session_state.bundle = backend.answer(*pending)
bundle = st.session_state.get("bundle")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title(":material/insights: Sherpa")
    st.caption("Governed AI analyst for payments data. The LLM plans and narrates; code computes every number.")
    persona = st.selectbox("Persona", list(access.personas), key="persona", format_func=lambda k: access.personas[k].label)
    st.caption(f"Regions: {', '.join(access.personas[persona].regions)}")
    mode = st.radio("Mode", ["Ask", "Explore", "Eval", "Runs"], key="mode")
    st.divider()
    st.markdown(f"**Data version:** {esc(bundle.data_version if bundle and bundle.data_version else '— (ask a question)')}")
    st.markdown(f"**As of:** {esc(f'{bundle.as_of:%d %b %Y}' if bundle and bundle.as_of else '—')}")
    used = bundle.llm_usage.get("backend") if bundle else None
    st.markdown(f"**LLM backend:** {esc(used or settings().llm_backend)}"
                + ("" if used else " (configured)"))
    if pipe is None:
        st.caption(":material/science: Fixture mode")



# ------------------------------------------------------------------ pages
def ask_page() -> None:
    st.header("Ask a question")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Question", key="question", on_change=ask_typed, width="stretch",
                      placeholder="e.g. Why did success rate drop last week?")
        st.button("Ask", type="primary", on_click=ask_typed, icon=":material/send:")
    st.pills("Demo questions", list(DEMO), key="chip_demo", on_change=ask_chip, args=("chip_demo",))
    st.pills("Verified questions (catalog)", [vq.question for vq in catalog.verified_queries],
             key="chip_vq", on_change=ask_chip, args=("chip_vq",))
    if bundle:
        st.divider()
        render.bundle(bundle, submit)


def explore_page() -> None:
    st.header("Explore")
    st.caption("Build a governed plan by hand. No LLM plans it; the same compiler, guard and checks run.")
    metrics = {m.name: m for m in catalog.metrics}
    c1, c2, c3 = st.columns(3)
    intent = c1.selectbox("Intent", get_args(Intent), index=get_args(Intent).index("breakdown"),
                          format_func=lambda i: i.replace("_", " "), key="x_intent")
    metric = metrics[c2.selectbox("Metric", list(metrics), format_func=lambda n: metrics[n].label, key="x_metric")]
    dims = [d for d in catalog.dimensions if metric.table in d.tables]
    dimensions = c3.multiselect("Dimensions" + (" (candidate drivers)" if intent == "explain_change" else ""),
                                [d.name for d in dims], format_func=lambda n: catalog.dimension(n).label, key="x_dims")
    c1, c2, c3 = st.columns(3)
    presets = get_args(WindowPreset)
    window = c1.selectbox("Window", presets, index=presets.index("last_7_days"),
                          format_func=lambda p: p.replace("_", " "), key="x_window")
    baseline = None
    if intent in ("compare_periods", "explain_change"):
        baseline = c2.selectbox("Baseline", [None, *presets], format_func=lambda p: "preceding window of equal length"
                                if p is None else p.replace("_", " "), key="x_baseline")
    grain = c3.radio("Grain", ["day", "hour"], horizontal=True, key="x_grain") if intent == "trend" else "day"
    filterable = [d for d in dims if d.values]
    filters = []
    for name in st.multiselect("Filter on", [d.name for d in filterable],
                               format_func=lambda n: catalog.dimension(n).label, key="x_filter_dims"):
        values = st.multiselect(f"{catalog.dimension(name).label} in", catalog.dimension(name).values, key=f"x_f_{name}")
        if values:
            filters.append(Filter(dimension=name, values=values))

    parts = [intent.replace("_", " ").capitalize() + ":", metric.label]
    if dimensions:
        parts.append("by " + ", ".join(catalog.dimension(d).label for d in dimensions))
    parts.append(window.replace("_", " "))
    if baseline:
        parts.append("vs " + baseline.replace("_", " "))
    if filters:
        parts.append("where " + "; ".join(f"{catalog.dimension(f.dimension).label} in {', '.join(f.values)}" for f in filters))
    if intent == "trend":
        parts.append(f"by {grain}")
    question = " ".join(parts)
    plan = AnalysisPlan(question=question, route="catalog", intent=intent, metric=metric.name, dimensions=dimensions,
                        filters=filters, window=TimeWindow(preset=window),
                        baseline=TimeWindow(preset=baseline) if baseline else None, grain=grain)
    st.markdown(f"**Question:** {esc(question)}")
    with st.expander("Plan JSON"):
        st.json(plan.model_dump(mode="json", exclude_defaults=True))
    st.button("Run plan", type="primary", icon=":material/play_arrow:", on_click=submit,
              args=(question, st.session_state.persona, plan))
    if bundle:
        st.divider()
        render.bundle(bundle, submit)


EVAL_METRICS = [  # key, label, format, higher is better
    ("result_equivalence", "Result equivalence", "pct", True), ("planted_causes", "Planted causes found", "pct", True),
    ("refusals", "Correct refusals", "pct", True), ("clarifications", "Correct clarifications", "pct", True),
    ("unsupported_numbers", "Unsupported numbers", "int", False), ("p50_ms", "p50 latency", "ms", False),
    ("cost_usd", "LLM cost", "usd", False),
]


def _fmt(v, fmt: str) -> str:
    if v is None:
        return "n/a"
    return {"pct": f"{v:.0%}", "int": f"{v:,.0f}", "ms": f"{v / 1000:.1f} s", "usd": f"${v:.2f}"}[fmt]


def eval_page() -> None:
    st.header("Eval: Sherpa vs a naive baseline")
    path = backend.EVAL_RESULTS
    if not path.exists() and pipe is None:
        path = backend.FIXTURES / "eval_latest.json"
        st.warning("Fixture mode: showing the demo eval results, not a real run.", icon=":material/science:")
    try:
        data = json.loads(path.read_text())
        systems, cases = data["systems"], data.get("cases", [])
    except FileNotFoundError:
        st.info(f"No eval results yet. Run the eval harness to write {backend.EVAL_RESULTS.relative_to(ROOT)}.",
                icon=":material/hourglass_empty:")
        return
    except (OSError, ValueError, KeyError, TypeError) as e:
        st.error(f"Could not read {esc(path.name)}: {esc(type(e).__name__)}: {esc(e)}", icon=":material/error:")
        return
    st.caption(f"Generated {esc(data.get('generated_at', '?'))} · data {esc(data.get('data_version', '?'))}")
    sherpa, base = systems.get("sherpa", {}), systems.get("baseline", {})
    cols = st.columns(4)
    for i, (key, label, fmt, higher) in enumerate(EVAL_METRICS):
        s, b = sherpa.get(key), base.get(key)
        cols[i % 4].metric(label, _fmt(s, fmt), delta=f"baseline {_fmt(b, fmt)}", delta_color="off",
                            delta_arrow="off", border=True)
    rows = [{"id": c.get("id"), "kind": c.get("kind"), "question": c.get("question"),
             "sherpa": "✅ pass" if c.get("sherpa", {}).get("pass") else "❌ fail", "sherpa detail": c.get("sherpa", {}).get("detail"),
             "baseline": "✅ pass" if c.get("baseline", {}).get("pass") else "❌ fail",
             "baseline detail": c.get("baseline", {}).get("detail")} for c in cases]
    st.markdown("##### Cases")
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def runs_page() -> None:
    st.header("Runs")
    try:
        from sherpa import runs
        stats, recent = runs.run_stats(), runs.recent_runs(50)
    except Exception as e:  # noqa: BLE001 - no DB / no runs module yet: say so instead of crashing the page
        st.info(f"Run history is unavailable ({esc(type(e).__name__)}: {esc(str(e).splitlines()[0] if str(e) else 'no detail')}). "
                "It needs the seeded database and sherpa.runs.", icon=":material/database_off:")
        return
    tiles = [("Runs", f"{stats.get('runs', 0):,}"), ("p50 latency", _fmt(stats.get("p50_ms"), "ms")),
             ("p95 latency", _fmt(stats.get("p95_ms"), "ms")), ("LLM cost", _fmt(stats.get("llm_cost_usd"), "usd")),
             ("Refusal rate", _fmt(stats.get("refusal_rate"), "pct")), ("Clarify rate", _fmt(stats.get("clarify_rate"), "pct")),
             ("Cache hit rate", _fmt(stats.get("cache_hit_rate"), "pct"))]
    cols = st.columns(4)
    for i, (label, value) in enumerate(tiles):
        cols[i % 4].metric(label, value, border=True)
    st.markdown("##### Recent runs")
    st.dataframe(pd.DataFrame(recent), hide_index=True)


if pipe is None and mode in ("Ask", "Explore"):
    st.info(f"**Fixture mode:** answers are canned demo bundles ({esc(fixture_reason)}).", icon=":material/science:")
{"Ask": ask_page, "Explore": explore_page, "Eval": eval_page, "Runs": runs_page}[mode]()
