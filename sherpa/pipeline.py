"""question -> AnswerBundle. The only entry point the UI and the eval call.

plan (LLM, or given by Explore / a clarification) -> triage -> resolve windows -> compiled SQL run as the
persona -> deterministic analysis -> Evidence -> narration (LLM or template) -> claim check -> confidence.
Never raises: failures become status="error" (or "refused" when a safety gate stopped a query).
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable

import pandas as pd

from . import charts, compiler, db, dq, drivers, llm, narrate, planner, reconcile, runs, triage
from .config import AMBIGUITY_THRESHOLD, MIN_RATE_DELTA, load_access, load_catalog
from .contracts import (AnalysisPlan, AnswerBundle, Clarification, ClarifyOption, Evidence, Filter,
                        QueryRejected, Refusal, TimeWindow, ValueFormat)

_FMT: dict[str, ValueFormat] = {"percent": "pct", "inr": "inr", "count": "int"}
_CHANGE_INTENTS = {"explain_change", "compare_periods"}


def _filters_text(filters: list[Filter]) -> list[str]:
    return [f"{f.dimension} {'in' if f.op == 'in' else 'not in'} ({', '.join(f.values)})" for f in filters]


class _Run:
    """Collects executed queries, evidence and timings for one answer."""

    def __init__(self, persona: str):
        self.persona = persona
        self.evidence: list[Evidence] = []
        self.timings: dict[str, int] = {}
        self.usage: dict[str, Any] = {}

    def q(self, sql: str, *, allow_truncated: bool = False):
        res = db.run_query(sql, self.persona)
        if res.truncated and not allow_truncated:
            # a cut-off breakdown silently drops groups (review R15); refuse rather than show a partial answer as complete
            raise QueryRejected("cost", f"The result has more than {res.row_count:,} rows, so it would be cut off. "
                                        "Narrow the window, add a filter or use fewer dimensions.", res.sql)
        self.timings["queries"] = self.timings.get("queries", 0) + 1
        self.timings["cache_hits"] = self.timings.get("cache_hits", 0) + int(res.cached)
        return res, res.df

    def add(self, **kw) -> Evidence:
        ev = Evidence(id=f"E{len(self.evidence) + 1}", **kw)
        self.evidence.append(ev)
        return ev

    def tick(self, name: str, t0: float) -> float:
        now = time.perf_counter()
        self.timings[name] = self.timings.get(name, 0) + int((now - t0) * 1000)
        return now


# ------------------------------------------------------------------ helpers over compiled SQL
def _overall(r: _Run, metric: str, window: TimeWindow, filters: list[Filter], baseline: TimeWindow | None = None):
    sql = compiler.compile_metric(metric, window=window, filters=filters, baseline=baseline)
    res, df = r.q(sql)
    out = {}
    if baseline is None:
        num, den = (float(df["num"].iloc[0] or 0), float(df["den"].iloc[0] or 0)) if len(df) else (0.0, 0.0)
        out["current"] = (num, den, compiler.metric_value(metric, num, den))
    else:
        for period in ("baseline", "current"):
            row = df[df["period"] == period]
            num = float(row["num"].sum()) if len(row) else 0.0
            den = float(row["den"].sum()) if len(row) else 0.0
            out[period] = (num, den, compiler.metric_value(metric, num, den))
    return res, out


def _frame(df: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    df = df.copy()
    for d in dims:
        df[d] = df[d].astype(object).where(df[d].notna(), "(none)").astype(str)
    df["num"] = df["num"].astype(float)
    df["den"] = df["den"].astype(float)
    return df


def _metric_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter]) -> None:
    m = load_catalog().metric(plan.metric)
    res, out = _overall(r, m.name, plan.window, filters)
    num, den, val = out["current"]
    r.add(kind="metric", title=f"{m.label}, {plan.window.label}", sql=[res.sql], sql_hashes=[res.sql_hash],
          tables=res.tables, filters=_filters_text(filters), window=plan.window.label, row_count=res.row_count,
          values={"value": val, "num": num, "den": den},
          formats={"value": _FMT[m.format], "num": "inr" if m.format == "inr" else "int", "den": "int"})


def _breakdown_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter]) -> None:
    m = load_catalog().metric(plan.metric)
    dims = plan.dimensions
    res_all, out = _overall(r, m.name, plan.window, filters)
    sql = compiler.compile_metric(m.name, window=plan.window, dimensions=dims, filters=filters)
    res, df = r.q(sql)
    df = _frame(df, dims)
    df["value"] = [compiler.metric_value(m.name, n, d) for n, d in zip(df["num"], df["den"])]
    # ratio metrics: biggest segments first (support); additive metrics: rank by the metric itself (top merchants by GMV)
    df = df.sort_values("den" if m.type == "ratio" else "value", ascending=False)
    df["segment"] = df[dims].astype(str).agg(" · ".join, axis=1)
    keys = drivers._keys({sg: sg for sg in df["segment"]})
    df["key"] = df["segment"].map(keys)
    values: dict[str, Any] = {"value": out["current"][2]}
    formats: dict[str, ValueFormat] = {"value": _FMT[m.format]}
    total_val, total_den = out["current"][2], float(df["den"].sum())
    for k, v, d in list(zip(df["key"], df["value"], df["den"]))[:25]:
        values[f"{k}_value"], formats[f"{k}_value"] = v, _FMT[m.format]
        values[f"{k}_den"], formats[f"{k}_den"] = d, "int"
        # concentration claims ("X had a quarter of GMV") must cite a computed share, never an eyeballed one
        if m.type == "simple" and total_val:
            values[f"{k}_share"], formats[f"{k}_share"] = (v or 0) / total_val, "pct"
        elif total_den:
            values[f"{k}_den_share"], formats[f"{k}_den_share"] = d / total_den, "pct"
    rows = df[["segment", "key", *dims, "value", "den"]].head(200).to_dict("records")
    r.add(kind="breakdown", title=f"{m.label} by {', '.join(dims)}, {plan.window.label}", sql=[res_all.sql, res.sql],
          sql_hashes=[res_all.sql_hash, res.sql_hash], tables=res.tables, filters=_filters_text(filters),
          window=plan.window.label, row_count=res.row_count, values=values, formats=formats, table=rows,
          chart=charts.bars(rows[:30], x="segment", y="value", fmt=_FMT[m.format]))


def _trend_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter], extra_title: str = "") -> Evidence:
    m = load_catalog().metric(plan.metric)
    sql = compiler.compile_metric(m.name, window=plan.window, dimensions=plan.dimensions[:1], filters=filters,
                                  grain=plan.grain)
    res, df = r.q(sql)
    df = _frame(df, plan.dimensions[:1])
    df["value"] = [compiler.metric_value(m.name, n, d) for n, d in zip(df["num"], df["den"])]
    if plan.grain == "hour":
        df["bucket"] = df["bucket_date"].astype(str) + " " + df["bucket_hour"].astype(int).map("{:02d}:00".format)
    else:
        df["bucket"] = df["bucket_date"].astype(str)
    clean = df.dropna(subset=["value"])
    values: dict[str, Any] = {}
    formats: dict[str, ValueFormat] = {}
    if len(clean) and not plan.dimensions:
        lo, hi = clean.loc[clean["value"].idxmin()], clean.loc[clean["value"].idxmax()]
        first, last = clean["value"].iloc[0], clean["value"].iloc[-1]
        values = {"first": first, "last": last, "change": last - first, "min": lo["value"], "min_at": lo["bucket"],
                  "max": hi["value"], "max_at": hi["bucket"], "median": float(clean["value"].median())}
        formats = {k: _FMT[m.format] for k in ("first", "last", "min", "max", "median")} | {
            "min_at": "text", "max_at": "text", "change": "pp" if m.format == "percent" else _FMT[m.format]}
    rows = df[["bucket", *plan.dimensions[:1], "value", "den"]].to_dict("records")  # contract: {bucket, value, den}
    return r.add(kind="trend", title=f"{m.label} by {plan.grain}{extra_title}, {plan.window.label}", sql=[res.sql],
                 sql_hashes=[res.sql_hash], tables=res.tables, filters=_filters_text(filters),
                 window=plan.window.label, row_count=res.row_count, values=values, formats=formats, table=rows[:200],
                 chart=charts.trend(rows, x="bucket", y="value", fmt=_FMT[m.format],
                                    color=plan.dimensions[0] if plan.dimensions else None))


def _compare_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter]) -> None:
    m = load_catalog().metric(plan.metric)
    res, out = _overall(r, m.name, plan.window, filters, plan.baseline)
    v0, v1 = out["baseline"][2], out["current"][2]
    dfmt: ValueFormat = "pp" if m.format == "percent" else _FMT[m.format]
    r.add(kind="comparison", title=f"{m.label}: {plan.window.label} vs {plan.baseline.label}", sql=[res.sql],
          sql_hashes=[res.sql_hash], tables=res.tables, filters=_filters_text(filters), window=plan.window.label,
          baseline=plan.baseline.label, row_count=res.row_count,
          values={"r0": v0, "r1": v1, "delta": None if v0 is None or v1 is None else v1 - v0,
                  "n0": out["baseline"][1], "n1": out["current"][1]},
          formats={"r0": _FMT[m.format], "r1": _FMT[m.format], "delta": dfmt, "n0": "int", "n1": "int"})
    if not plan.dimensions:
        return
    sql = compiler.compile_metric(m.name, window=plan.window, baseline=plan.baseline,
                                  dimensions=plan.dimensions, filters=filters)
    res, df = r.q(sql)
    df = _frame(df, plan.dimensions)
    df["segment"] = df[plan.dimensions].astype(str).agg(" · ".join, axis=1)
    agg = df.groupby(["segment", "period"])[["num", "den"]].sum()
    keys = drivers._keys({sg: sg for sg in df["segment"].unique()})
    rows, values, formats = [], {}, {}
    for sg, k in keys.items():
        n0, d0 = agg.loc[(sg, "baseline")] if (sg, "baseline") in agg.index else (0.0, 0.0)
        n1, d1 = agg.loc[(sg, "current")] if (sg, "current") in agg.index else (0.0, 0.0)
        a, b = compiler.metric_value(m.name, n0, d0), compiler.metric_value(m.name, n1, d1)
        dd = None if a is None or b is None else b - a
        rows.append({"segment": sg, "key": k, "r0": a, "r1": b, "delta": dd, "n0": d0, "n1": d1})
        values |= {f"{k}_r0": a, f"{k}_r1": b, f"{k}_delta": dd}
        formats |= {f"{k}_r0": _FMT[m.format], f"{k}_r1": _FMT[m.format], f"{k}_delta": dfmt}
    rows.sort(key=lambda x: -(x["n1"] or 0))
    r.add(kind="comparison", title=f"{m.label} by {', '.join(plan.dimensions)}: {plan.window.label} vs {plan.baseline.label}",
          sql=[res.sql], sql_hashes=[res.sql_hash], tables=res.tables, filters=_filters_text(filters),
          window=plan.window.label, baseline=plan.baseline.label, row_count=res.row_count,
          values=values, formats=formats, table=rows[:200],
          chart=charts.bars([{"segment": x["segment"], "value": x["delta"]} for x in rows[:30] if x["delta"] is not None],
                            x="segment", y="value", fmt=dfmt))


def _explain_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter]):
    cat = load_catalog()
    m = cat.metric(plan.metric)
    if m.type != "ratio":
        # Additive metrics: a change is the sum of segment changes; no mix/rate split needed.
        default = next(d.name for d in cat.dimensions if d.driver and m.table in d.tables)
        _compare_evidence(r, plan.model_copy(update={"dimensions": plan.dimensions or [default]}), filters)
        return None
    single = {f.dimension for f in filters if f.op == "in" and len(f.values) == 1}
    dims = plan.dimensions or [d.name for d in cat.dimensions if d.driver and m.table in d.tables and d.name not in single]
    sqls: list[str] = []
    hashes: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    for d in dims:
        res, df = r.q(compiler.compile_metric(m.name, window=plan.window, baseline=plan.baseline, dimensions=[d], filters=filters))
        frames[d] = _frame(df, [d])
        sqls.append(res.sql)
        hashes.append(res.sql_hash)
    kw = dict(metric=m.name, window=plan.window.label, baseline=plan.baseline.label)
    report = drivers.explain_change(frames, **kw)
    top3 = [x.dimension for x in report.dimensions[:3]]
    pairs = [(top3[i], top3[j]) for i in range(len(top3)) for j in range(i + 1, len(top3))]
    span = (plan.window.end - plan.window.start).days + 1
    if top3 and span <= 2 and "txn_hour" in dims and top3[0] != "txn_hour":
        pairs.append((top3[0], "txn_hour"))          # outages are hour-shaped on short windows
    if "CARD" in {v for f in filters if f.dimension == "payment_method" for v in f.values} \
            and {"issuer_bank", "card_network"} <= set(dims):
        pairs.append(("issuer_bank", "card_network"))  # issuer x scheme is where 3DS/ACS breaks show up
    seen: set[frozenset] = set()
    pairs = [x for x in pairs if not (frozenset(x) in seen or seen.add(frozenset(x)))]
    drill: dict[tuple[str, str], pd.DataFrame] = {}
    for pair in pairs:
            res, df = r.q(compiler.compile_metric(m.name, window=plan.window, baseline=plan.baseline,
                                                  dimensions=list(pair), filters=filters))
            drill[pair] = _frame(df, list(pair))
            sqls.append(res.sql)
            hashes.append(res.sql_hash)
    if drill:
        report = drivers.explain_change(frames, drill=drill, **kw)
    evs = drivers.evidence_from_report(report, start_id=len(r.evidence) + 1)
    for ev in evs:
        ev.sql, ev.sql_hashes = (ev.sql or sqls), (ev.sql_hashes or hashes)
        ev.tables = ev.tables or ["transactions"]
        ev.filters = ev.filters or _filters_text(filters)
        ev.window, ev.baseline = ev.window or plan.window.label, ev.baseline or plan.baseline.label
    if report.dimensions:
        top = report.dimensions[0]
        # evidence_from_report emits decompositions in rank order, so the first one is the top dimension
        target = next((e for e in evs if e.kind == "decomposition"), None)
        if target is not None:
            target.chart = target.chart or charts.waterfall(top)
    r.evidence.extend(evs)

    # Decline split (technical vs business) overall and in the top segment: what kind of failure moved.
    if m.name in ("success_rate", "success_rate_incl_dropoffs") and report.dimensions:
        scopes = [("overall", filters)]
        top = report.dimensions[0]
        if top.segments and top.segments[0].segment != "(none)":
            seg = top.segments[0]
            scopes.append((f"{top.dimension}={seg.segment}", filters + [Filter(dimension=top.dimension, values=[seg.segment])]))
        for label, flt in scopes:
            vals, fmts, s, h = {}, {}, [], []
            for short, mn in (("td", "technical_decline_rate"), ("bd", "business_decline_rate")):
                res, out = _overall(r, mn, plan.window, flt, plan.baseline)
                a, b = out["baseline"][2], out["current"][2]
                vals |= {f"{short}_r0": a, f"{short}_r1": b, f"{short}_delta": None if a is None or b is None else b - a}
                fmts |= {f"{short}_r0": "pct", f"{short}_r1": "pct", f"{short}_delta": "pp"}
                s.append(res.sql)
                h.append(res.sql_hash)
            r.add(kind="segment_test", title=f"Technical vs business declines ({label})", sql=s, sql_hashes=h,
                  tables=["transactions"], filters=_filters_text(flt), window=plan.window.label,
                  baseline=plan.baseline.label, values=vals, formats=fmts)
        # Short windows: when in the day did the top segment break?
        if span <= 2 and len(scopes) > 1:
            hp = plan.model_copy(update={"grain": "hour", "dimensions": []})
            _trend_evidence(r, hp, scopes[1][1], extra_title=f" for {scopes[1][0]}")
    return report


def _recon_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter]):
    qs = compiler.compile_recon_queries(plan.window, filters)
    frames, sqls, hashes = {}, [], []
    for name, sql in qs.items():
        res, df = r.q(sql)
        frames[name] = df
        sqls.append(res.sql)
        hashes.append(res.sql_hash)
    rec = reconcile.reconcile(frames["by_txn_date"], frames["by_cycle_date"], frames["settlements"], window=plan.window)
    values = {"txn_gmv_inr": rec.txn_gmv_inr, "settled_net_inr": rec.settled_net_inr, "gap_inr": rec.gap_inr}
    values |= {c.name: c.amount_inr for c in rec.components}
    r.add(kind="reconciliation", title=f"Transactions vs settlements, {plan.window.label}", sql=sqls,
          sql_hashes=hashes, tables=["transactions", "settlements"], filters=_filters_text(filters),
          window=plan.window.label, values=values, formats={k: "inr" for k in values},
          table=[c.model_dump() for c in rec.components], chart=charts.recon_bridge(rec))
    return rec


def _dq_evidence(r: _Run, plan: AnalysisPlan, filters: list[Filter], as_of) -> list:
    start = min(plan.window.start, plan.baseline.start) if plan.baseline else plan.window.start
    span = TimeWindow(start=start, end=plan.window.end, label=f"{start} to {plan.window.end}")
    region_only = [f for f in filters if f.dimension == "region"]
    qs = compiler.compile_dq_queries(span, region_only)
    res1, dq_daily = r.q(qs["dq_daily"])
    res2, hourly = r.q(qs["hourly"])
    warnings = dq.run_checks(dq_daily, hourly, window=span, as_of=as_of)
    common = dict(sql=[res1.sql, res2.sql], sql_hashes=[res1.sql_hash, res2.sql_hash], tables=["dq_daily", "transactions"],
                  filters=_filters_text(region_only), window=span.label)
    for w in warnings:
        vals = dict(w.values) | {"check": w.check, "severity": w.severity, "message": w.message}
        fmts = {k: ("text" if isinstance(v, str) or v is None else "int" if float(v).is_integer() else "float")
                for k, v in vals.items()}
        r.add(kind="dq_check", title=f"Data quality: {w.message}", values=vals, formats=fmts, **common)
    if plan.intent == "data_quality" and not warnings:
        raw = int(dq_daily["raw_events"].sum()) if len(dq_daily) else 0
        dup = int(dq_daily["duplicate_events"].sum()) if len(dq_daily) else 0
        r.add(kind="dq_check", title=f"Data quality: no issues found, {span.label}",
              values={"check": "all", "severity": "info", "raw_events": raw, "duplicate_events": dup},
              formats={"check": "text", "severity": "text", "raw_events": "int", "duplicate_events": "int"}, **common)
    return warnings


def _sql_route_evidence(r: _Run, plan: AnalysisPlan) -> None:
    res, df = r.q(plan.sql, allow_truncated=True)
    values, formats = {}, {}
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    for i, row in df.head(20).iterrows():
        for c in num_cols:
            k = f"r{i + 1}_{drivers._keys({c: c})[c]}"
            values[k] = None if pd.isna(row[c]) else float(row[c])
            formats[k] = "pct" if ("rate" in c.lower() and abs(values[k] or 0) <= 1) else "float"
    title = "Result of model-written SQL (unverified" + (f", first {res.row_count:,} rows only)" if res.truncated else ")")
    r.add(kind="breakdown", title=title, sql=[res.sql], sql_hashes=[res.sql_hash],
          tables=res.tables, row_count=res.row_count, values=values, formats=formats,
          table=df.head(200).astype(object).where(df.head(200).notna(), None).to_dict("records"))


# ------------------------------------------------------------------ ambiguity: compute every reading, ask only if it matters
def _denominator_check(r: _Run, plan: AnalysisPlan, filters: list[Filter], variants: list[str]):
    cat = load_catalog()
    readings = {}
    change = plan.intent in _CHANGE_INTENTS
    for mn in [plan.metric, *variants]:
        _, out = _overall(r, mn, plan.window, filters, plan.baseline if change else None)
        if change:
            a, b = out["baseline"][2], out["current"][2]
            readings[mn] = None if a is None or b is None else b - a
        else:
            readings[mn] = out["current"][2]
    vals = [v for v in readings.values() if v is not None]
    if change:
        # Ask only when the readings tell different stories: opposite directions, or material under one and not the other.
        # Two drops of different size answer "why did it drop?" the same way, so we state the assumption instead.
        # Different stories: opposite directions (both clearly non-zero), or one material while the other is flat.
        # The half-threshold dead zone keeps a -0.59 pp vs -0.27 pp pair (both "a drop") from flipping on a 0.3 pp edge.
        flat, material = MIN_RATE_DELTA / 2, MIN_RATE_DELTA

        def differ(a: float, b: float) -> bool:
            if abs(a) >= flat and abs(b) >= flat and (a > 0) != (b > 0):
                return True
            return max(abs(a), abs(b)) >= material and min(abs(a), abs(b)) < flat

        agree = not any(differ(a, b) for i, a in enumerate(vals) for b in vals[i + 1:])
    else:
        agree = len(vals) < 2 or max(vals) - min(vals) <= AMBIGUITY_THRESHOLD
    if agree or plan.intent not in (*_CHANGE_INTENTS, "metric_value"):
        alt = ", ".join(f"{cat.metric(k).label}: {'change ' if change else ''}"
                        f"{(v * 100 if v is not None else float('nan')):+.2f}{' pp' if change else '%'}"
                        for k, v in readings.items() if k != plan.metric and v is not None)
        note = f"Used {cat.metric(plan.metric).label} ({cat.metric(plan.metric).description.split('.')[0].lower()})."
        return None, note + (f" The other definition tells the same story ({alt})." if alt and change else
                             (f" Other definition for reference: {alt}." if alt else ""))
    opts = []
    for mn, v in readings.items():
        prev = None if v is None else (f"{v * 100:+.2f} pp" if change else f"{v * 100:.1f}%")
        opts.append(ClarifyOption(label=cat.metric(mn).label + " — " + cat.metric(mn).description.split(".")[0],
                                  plan_patch={"metric": mn, "ambiguities": []}, preview=prev))
    q = ("These two definitions of success rate move differently over this period. Which one do you mean?"
         if change else "Which success-rate definition do you mean?")
    return Clarification(question=q, options=opts), None


# ------------------------------------------------------------------ entry point
def answer(question: str, persona: str, *, plan: AnalysisPlan | None = None,
           on_stage: Callable[[str], None] | None = None) -> AnswerBundle:
    """on_stage(name) is called as each stage starts: plan, triage, analysis, dq, narrate, check. It can never break a run."""
    t_start = time.perf_counter()
    r = _Run(persona)

    def stage(name: str) -> None:
        if on_stage is not None:
            try:
                on_stage(name)
            except Exception:
                pass

    bundle = AnswerBundle(run_id=uuid.uuid4().hex[:12], question=question, persona=persona, status="error")
    try:
        load_access().persona(persona)
        dv = db.data_version(persona)
        bundle.data_version = dv["version"]
        as_of, data_start = dv["as_of"], dv["data_start"]
        bundle.as_of = as_of

        t = time.perf_counter()
        stage("plan")
        if plan is None:
            try:
                plan, u = planner.plan(question, persona, as_of=as_of, data_start=data_start)
                r.usage["planner"] = u
            except llm.LLMUnavailable as e:
                bundle.error = f"No language model is available ({e}). Use Explore mode, which needs no LLM."
                return bundle
        t = r.tick("plan", t)

        stage("triage")
        tri = triage.triage(plan, persona)
        bundle.plan = tri.plan
        t = r.tick("triage", t)
        if tri.action == "refuse":
            bundle.status, bundle.refusal, bundle.clarification = "refused", tri.refusal, tri.clarification
            return bundle
        if tri.action == "clarify":
            bundle.status, bundle.clarification = "clarify", tri.clarification
            return bundle

        plan = tri.plan
        win = compiler.resolve_window(plan.window or TimeWindow(preset="last_7_days"), as_of, data_start)
        base = None
        if plan.intent in _CHANGE_INTENTS:
            base = compiler.resolve_window(plan.baseline or compiler.default_baseline(win), as_of, data_start)
            wlen, blen = (win.end - win.start).days + 1, (base.end - base.start).days + 1
            if plan.baseline is None and blen != wlen:
                # The data starts too late for a same-length comparison (review R13). Totals over different spans are not
                # comparable; rates are, if we say so.
                mdef = load_catalog().metric(plan.metric) if plan.metric else None
                if mdef is None or mdef.type == "simple":
                    bundle.status = "refused"
                    bundle.refusal = Refusal(
                        reason=f"Only {blen} day(s) of data exist before {win.label}, so a same-length comparison is not possible "
                               f"for a total. Comparing {wlen} days with {blen} would show a fake jump.",
                        suggestion="Pick a shorter window (for example the last 7 days), or compare a rate instead of a total.")
                    return bundle
                plan.assumptions.append(f"The comparison period is shortened to {base.label} ({blen} days) because the data starts "
                                        f"on {data_start}. Rates are comparable across different lengths.")
        plan = plan.model_copy(update={"window": win, "baseline": base})
        bundle.plan, bundle.route = plan, plan.route

        filters = plan.filters
        stage("analysis")
        if plan.route == "sql":
            _sql_route_evidence(r, plan)
        else:
            if tri.variant_metrics:
                clar, note = _denominator_check(r, plan, filters, tri.variant_metrics)
                if clar:
                    bundle.status, bundle.clarification = "clarify", clar
                    return bundle
                if note:
                    plan.assumptions.append(note)
            intent = plan.intent
            if intent == "metric_value":
                _metric_evidence(r, plan, filters)
            elif intent == "breakdown":
                if not plan.dimensions:
                    _metric_evidence(r, plan, filters)
                else:
                    _breakdown_evidence(r, plan, filters)
            elif intent == "trend":
                _trend_evidence(r, plan, filters)
            elif intent == "compare_periods":
                _compare_evidence(r, plan, filters)
            elif intent == "explain_change":
                bundle.drivers = _explain_evidence(r, plan, filters)
            elif intent == "reconcile":
                bundle.recon = _recon_evidence(r, plan, filters)
        t = r.tick("analysis", t)

        if plan.route == "sql" or (plan.metric and load_catalog().metric(plan.metric).table == "transactions") or plan.intent in ("data_quality", "reconcile"):
            stage("dq")
            bundle.dq = _dq_evidence(r, plan, filters, as_of)
        t = r.tick("dq", t)

        stage("narrate")
        try:
            narr, u = narrate.narrate(question, plan, r.evidence, drivers=bundle.drivers, dq=bundle.dq)
            r.usage["narrator"] = u
        except llm.LLMUnavailable:
            narr = narrate.template_narrative(plan, r.evidence, drivers=bundle.drivers, dq=bundle.dq)
            r.usage["narrator"] = {"backend": "template"}
        t = r.tick("narrate", t)
        stage("check")
        bundle.headline, bundle.claims = narrate.check_claims(narr, r.evidence)
        t = r.tick("check", t)

        bundle.confidence, bundle.confidence_reasons = narrate.confidence(
            plan, plan.route, r.evidence, bundle.claims, bundle.dq, bundle.drivers,
            dropped_claims=int((r.usage.get("narrator") or {}).get("dropped_claims") or 0))
        bundle.status = "answered"
    except QueryRejected as e:
        bundle.status = "refused"
        bundle.refusal = Refusal(reason=f"The query was stopped by the {e.stage} check: {e.reason}",
                                 suggestion="Rephrase using the governed metrics, or narrow the time window.")
    except Exception as e:  # never let one bad answer take the app down
        bundle.status, bundle.error = "error", f"{type(e).__name__}: {e}"
    finally:
        bundle.evidence = r.evidence
        bundle.timings_ms = {**r.timings, "total": int((time.perf_counter() - t_start) * 1000)}
        narr_backend = (r.usage.get("narrator") or {}).get("backend")
        bundle.llm_usage = r.usage | {
            "backend": narr_backend if narr_backend == "template" else _safe_backend(),
            "cost_usd": round(sum(float(u.get("cost_usd") or 0) for u in r.usage.values() if isinstance(u, dict)), 5)}
        runs.save_run(bundle)
    return bundle


def _safe_backend() -> str:
    try:
        return llm.backend()
    except Exception:
        return "none"
