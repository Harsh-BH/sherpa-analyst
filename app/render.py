"""Render an AnswerBundle. Security rule: every data-derived string goes through esc() (inert Markdown),
st.code, st.dataframe or a Vega-Lite chart. Nothing here uses unsafe_allow_html."""
from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd
import streamlit as st

from sherpa import charts
from sherpa.config import load_catalog
from sherpa.contracts import AnalysisPlan, AnswerBundle, DimensionDecomposition, Evidence, SegmentEffect, format_value

from .backend import patched

# Every character that Markdown, HTML, LaTeX ($) or Streamlit directives (:red[..], :material/x:) act on.
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:=&\"'^%@])")
KINDS = {  # claim kind -> (tag, badge colour, icon); the tag text means it never relies on colour alone
    "fact": ("Fact", "blue", ":material/fact_check:"),
    "hypothesis": ("Hypothesis", "violet", ":material/psychology:"),
    "recommendation": ("Recommendation", "green", ":material/lightbulb:"),
    "caveat": ("Caveat", "orange", ":material/warning:"),
}
CONFIDENCE = {"high": "green", "medium": "orange", "low": "red"}
SEVERITY = {"error": (st.error, ":material/error:"), "warn": (st.warning, ":material/warning:"),
            "info": (st.info, ":material/info:")}

Submit = Callable[[str, str, AnalysisPlan | None], None]   # (question, persona, plan) -> queue a run


def esc(s: object) -> str:
    """Data-derived text -> Markdown that renders exactly as the text (no links, HTML, LaTeX or directives)."""
    return _MD_SPECIAL.sub(r"\\\1", str(s)).replace("\n", "  \n")


def bundle(b: AnswerBundle, submit: Submit) -> None:
    if b.status == "error":
        return error_card(b)
    if b.status == "clarify":
        return clarification(b, submit)
    if b.status == "refused":
        return refusal(b, submit)
    answered(b)


def error_card(b: AnswerBundle) -> None:
    with st.container(border=True):
        st.error(f"**This run failed.** {esc(b.error or 'No error message was recorded.')}", icon=":material/error:")
        st.markdown(f"Question: {esc(b.question)}")
        st.caption("Run id (quote it when reporting the problem):")
        st.code(b.run_id, language=None)


def clarification(b: AnswerBundle, submit: Submit) -> None:
    c = b.clarification
    with st.container(border=True):
        st.markdown(f"#### :material/help: {esc(c.question if c else 'Sherpa needs a clarification.')}")
        st.caption(f"Your question: {esc(b.question)}")
        for i, opt in enumerate(c.options if c else []):
            label = esc(opt.label) + (f" · **{esc(opt.preview)}**" if opt.preview else "")
            st.button(label, key=f"clarify-{b.run_id}-{i}", disabled=b.plan is None, width="stretch",
                      on_click=submit, args=(b.question, b.persona, b.plan and patched(b.plan, opt.plan_patch)))


def refusal(b: AnswerBundle, submit: Submit) -> None:
    r = b.refusal
    with st.container(border=True):
        st.markdown("#### :material/block: Not answered")
        st.error(esc(r.reason if r else "This request was refused."), icon=":material/lock:")
        if r and r.suggestion:
            st.info(esc(r.suggestion), icon=":material/lightbulb:")
        if r and r.plan_patch and b.plan:
            st.button("Show me that instead", type="primary", key=f"refusal-{b.run_id}",
                      on_click=submit, args=(b.question, b.persona, patched(b.plan, r.plan_patch)))
        st.caption(f"Run {esc(b.run_id)} · persona {esc(b.persona)}")


def answered(b: AnswerBundle) -> None:
    for w in b.dq:  # data-quality banner first: it qualifies everything below
        alert, icon = SEVERITY[w.severity]
        alert(f"**Data quality · {esc(w.check.replace('_', ' '))}:** {esc(w.message)}", icon=icon)
    with st.container(border=True):
        st.markdown(f"### {esc(b.headline or 'No headline was produced.')}")
        with st.container(horizontal=True, gap="small"):
            if b.confidence:
                st.badge(f"{b.confidence.capitalize()} confidence", icon=":material/speed:", color=CONFIDENCE[b.confidence])
            if b.route == "sql":
                st.badge("Unverified SQL", icon=":material/warning:", color="red")
            elif b.route == "catalog":
                st.badge("Governed metric", icon=":material/verified:", color="blue")
        meta = [f"run {b.run_id}", f"persona {b.persona}", b.data_version and f"data {b.data_version}",
                b.as_of and f"as of {b.as_of:%d %b %Y}", "total" in b.timings_ms and f"{b.timings_ms['total'] / 1000:.1f} s",
                isinstance(b.llm_usage.get("cost_usd"), int | float) and f"LLM ${b.llm_usage['cost_usd']:.4f}"]
        st.caption(" · ".join(esc(m) for m in meta if m))
        if b.route == "sql":
            st.warning("**Unverified SQL.** The model wrote this query; it passed the guard but is not a governed "
                       "metric, so confidence is capped at medium. Check the SQL in the evidence below.",
                       icon=":material/warning:")
        if b.confidence_reasons:
            with st.expander(f"Why {esc(b.confidence or 'this')} confidence"):
                st.markdown("\n".join(f"- {esc(r)}" for r in b.confidence_reasons))
        if b.plan and b.plan.assumptions:
            st.markdown("**Assumptions**\n" + "\n".join(f"- {esc(a)}" for a in b.plan.assumptions))

    by_id = {e.id: e for e in b.evidence}
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown("##### What the evidence says")
        claims(b, by_id)
    with right:
        key_chart(b)
    if b.drivers:
        driver_tables(b)
    if b.recon:
        st.markdown("##### Reconciliation components")
        st.dataframe(pd.DataFrame([{"component": c.name.replace("_", " "), "amount": format_value(c.amount_inr, "inr"),
                                    "note": c.note} for c in b.recon.components]), hide_index=True)
        st.caption(f"Source of truth: {esc(b.recon.source_of_truth)}")
    evidence_panel(b.evidence, percent_metric=_is_percent(b.plan.metric if b.plan else None))
    st.download_button("Download run bundle", data=b.model_dump_json(indent=2), mime="application/json",
                       file_name=f"sherpa-run-{re.sub(r'[^A-Za-z0-9_.-]', '_', b.run_id)}.json",
                       icon=":material/download:")


def claims(b: AnswerBundle, by_id: dict[str, Evidence]) -> None:
    for kind, (tag, color, icon) in KINDS.items():
        for i, c in enumerate(x for x in b.claims if x.kind == kind):
            st.markdown(f":{color}-badge[{icon} {tag}] {esc(c.rendered)}")
            if not c.ok:
                st.caption(":material/report: Claim checker: " + esc("; ".join(c.problems) or "failed"))
            if c.evidence_ids:
                with st.container(horizontal=True, gap="small"):
                    for eid in dict.fromkeys(c.evidence_ids):
                        e = by_id.get(eid)
                        with st.popover(esc(eid), icon=":material/database:", key=f"pop-{kind}-{i}-{eid}",
                                        help=esc(e.title) if e else "Evidence not found in this bundle"):
                            if e:
                                evidence_meta(e)
                                sql_blocks(e)
                            else:
                                st.warning(f"No evidence {esc(eid)} in this bundle.")


def key_chart(b: AnswerBundle) -> None:
    """The chart that sits next to the claims: the driver waterfall, the recon bridge, or the first evidence chart."""
    if b.drivers and b.drivers.dimensions:
        dims = {d.dimension: d for d in b.drivers.dimensions}
        names = list(dims)
        pick = st.selectbox("Decompose by", names, index=names.index(b.drivers.top_dimension)
                            if b.drivers.top_dimension in dims else 0, format_func=lambda n: n.replace("_", " "),
                            key=f"dim-{b.run_id}")
        dec = dims[pick]
        st.vega_lite_chart(charts.waterfall(dec), width="stretch")
        simpson_callout(b, dec)
        for note in b.drivers.notes:
            st.caption(esc(note))
    elif b.recon:
        st.vega_lite_chart(charts.recon_bridge(b.recon), width="stretch")
    elif chart := next((e for e in b.evidence if e.chart), None):
        st.vega_lite_chart(chart.chart, width="stretch")
        st.caption(f"{esc(chart.id)} · {esc(chart.title)}")


def simpson_callout(b: AnswerBundle, dec: DimensionDecomposition) -> None:
    dim = dec.dimension.replace("_", " ")
    if dec.simpson_flag:
        toward = "lower" if dec.mix_total < 0 else "higher"
        st.info(f"**Simpson's paradox.** The overall rate moved {esc(format_value(dec.delta, 'pp'))}, but "
                f"{esc(format_value(dec.mix_total, 'pp'))} of it is mix (volume moved toward {toward}-rate "
                f"{esc(dim)} values) and only {esc(format_value(dec.rate_total, 'pp'))} is rate change within them, "
                f"so no {esc(dim)} got worse.", icon=":material/call_split:")
    else:
        st.caption(f"By {esc(dim)}: mix {esc(format_value(dec.mix_total, 'pp'))}, "
                   f"rate {esc(format_value(dec.rate_total, 'pp'))}.")


def _effects_df(effects: list[tuple[str, SegmentEffect]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "segment": label, **{col: None if v is None else v * 100 for col, v in
                             (("share before", e.share0), ("share now", e.share1), ("rate before", e.rate0), ("rate now", e.rate1))},
        "mix (pp)": e.mix_effect * 100, "rate (pp)": e.rate_effect * 100, "total (pp)": e.total_effect * 100,
        "z": e.z, "q (BH)": e.q_value, "supported": e.supported, "significant": e.significant, "material": e.material,
    } for label, e in effects])


EFFECT_COLUMNS = {
    **{c: st.column_config.NumberColumn(format="%.1f%%") for c in ("share before", "share now", "rate before", "rate now")},
    **{c: st.column_config.NumberColumn(format="%+.2f pp") for c in ("mix (pp)", "rate (pp)", "total (pp)")},
    "z": st.column_config.NumberColumn(format="%.2f"), "q (BH)": st.column_config.NumberColumn(format="%.2g"),
}


def driver_tables(b: AnswerBundle) -> None:
    d = b.drivers
    try:
        metric = load_catalog().metric(d.metric).label
    except KeyError:
        metric = d.metric
    st.markdown(f"##### Segments · {esc(metric)}: {esc(format_value(d.r0, 'pct'))} → {esc(format_value(d.r1, 'pct'))} "
                f"({esc(format_value(d.delta, 'pp'))}), {esc(d.window)} vs {esc(d.baseline)}")
    for dec in d.dimensions:
        st.caption(f"{esc(dec.dimension.replace('_', ' '))} · explanatory score {dec.score:.2f}"
                   + (" · Simpson flag" if dec.simpson_flag else ""))
        st.dataframe(_effects_df([(s.segment, s) for s in dec.segments]), hide_index=True, column_config=EFFECT_COLUMNS)
    if d.drilldown:
        st.markdown("##### Drill-down cells")
        st.dataframe(_effects_df([(" × ".join(f"{k}={v}" for k, v in c.dims.items()), c.effect) for c in d.drilldown]),
                     hide_index=True, column_config=EFFECT_COLUMNS)


def evidence_meta(e: Evidence) -> None:
    st.markdown(f"**{esc(e.id)} · {esc(e.title)}**")
    rows = [("Window", e.window), ("Baseline", e.baseline), ("Filters", ", ".join(e.filters) or "none"),
            ("Tables", ", ".join(e.tables)), ("Rows", e.row_count)]
    st.markdown("\n".join(f"- **{k}:** {esc(v)}" for k, v in rows if v is not None))


def sql_blocks(e: Evidence) -> None:
    for i, sql in enumerate(e.sql):
        h = e.sql_hashes[i] if i < len(e.sql_hashes) else "n/a"
        st.caption(f"SQL {i + 1} of {len(e.sql)} · sha256 {esc(h)}")
        st.code(sql, language="sql", wrap_lines=True)


def value_text(e: Evidence, key: str) -> str:
    v = e.values[key]
    return format_value(v, e.formats.get(key, "text" if isinstance(v, str) else "float"))


def _is_percent(metric: str | None) -> bool:
    try:
        return load_catalog().metric(metric).format == "percent"
    except KeyError:
        return False


def table_df(e: Evidence, percent_metric: bool = False) -> pd.DataFrame:
    """Result table rendered like the claims. A column takes Evidence.formats[col] or the format of any
    `<segkey>_<col>` key; failing that, 0..1 columns named *rate* (or `value` on a percent metric) are pct
    and *_inr columns are inr. Non-numeric columns are left as they are."""
    df = pd.DataFrame(e.table)
    for col in df.columns:
        name = str(col)
        nums = pd.to_numeric(df[col], errors="coerce")
        if df[col].dtype == bool or not nums.notna().all():
            continue
        fmt = e.formats.get(name) or next((f for k, f in e.formats.items() if k.endswith(f"_{name}")), None)
        if fmt is None and ("rate" in name or (name == "value" and percent_metric)) and nums.between(0, 1).all():
            fmt = "pct"
        elif fmt is None and name.endswith("_inr"):
            fmt = "inr"
        if fmt and fmt not in ("text", "date"):
            df[col] = [format_value(v, fmt) for v in nums]
    return df


def evidence_panel(evidence: list[Evidence], percent_metric: bool = False) -> None:
    if not evidence:
        return
    st.markdown("##### Evidence")
    for e, tab in zip(evidence, st.tabs([f"{esc(e.id)} · {esc(e.title)}" for e in evidence])):
        with tab:
            left, right = st.columns([1, 1.2], gap="large")
            with left:
                evidence_meta(e)
                sql_blocks(e)
            with right:
                if e.chart:
                    st.vega_lite_chart(e.chart, width="stretch")
                if e.values:
                    st.caption("Values claims can cite")
                    st.dataframe(pd.DataFrame([{"placeholder": f"{{{e.id}.{k}}}", "value": value_text(e, k)}
                                               for k in e.values]), hide_index=True)
            if e.table:
                st.caption(f"Result table ({len(e.table)} rows)")
                st.dataframe(table_df(e, percent_metric), hide_index=True)
