"""Driver engine: why did a ratio metric move between two periods?

Pure pandas in, contract models out (docs/CONTRACTS.md §3). The rate/mix formulas are in
docs/ARCHITECTURE.md "Driver engine"; thresholds come from sherpa/config.py.
"""
from __future__ import annotations

import re
from itertools import count

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportions_ztest

from .config import (FDR_Q, MIN_CONTRIBUTION, MIN_RATE_DELTA, MIN_SHARE, MIN_SUPPORT, SIMPSON_MIX_SHARE,
                     load_catalog)
from .contracts import DimensionDecomposition, DrillCell, DriverReport, Evidence, SegmentEffect, ValueFormat

NONE_LABEL = "(none)"     # segment label for NULL dimension values (card_network on UPI, issuer on WALLET)
DRILL_TOP = 5             # drill-down cells returned
ADTRIBUTOR_TEEP = 0.1     # Adtributor's per-element explanatory-power threshold (Bhagwan et al. 2014)
PERIODS = ("baseline", "current")


# ---------------------------------------------------------------- decomposition
def decompose(df: pd.DataFrame, dimension: str) -> DimensionDecomposition:
    """Symmetric (Kitagawa 1955 / Das Gupta 1993) rate/mix split of R = num/den over one dimension.

    df: [<dimension>, "period", "num", "den"], period in {"baseline", "current"}.
    Per segment i (share c = n/N, rate r = s/n, R̄ = (R0 + R1)/2):
        mix_i  = (c1 - c0) * ((r0 + r1)/2 - R̄)        rate_i = (r1 - r0) * (c0 + c1)/2
    and Σmix + Σrate == R1 - R0 exactly. A segment present in one period only takes the other period's
    rate, so its whole effect is mix. Each segment gets a two-proportion z-test when the numerator is a
    count of the denominator's rows (integral and 0 <= num <= den); sum numerators (avg_ticket_size) get
    none. Standalone, `significant` uses raw p < FDR_Q; explain_change replaces it with BH q-values.
    """
    return _judge(_decompose(df, dimension))


def _decompose(df: pd.DataFrame, dimension: str) -> DimensionDecomposition:
    bad = set(df["period"]) - set(PERIODS)
    if bad:
        raise ValueError(f"unknown period values {sorted(bad)}; expected {PERIODS}")
    seg = df[dimension].astype(object).where(df[dimension].notna(), NONE_LABEL).astype(str)
    g = (df.assign(_seg=seg).groupby(["_seg", "period"])[["num", "den"]].sum()
         .unstack("period", fill_value=0)
         .reindex(columns=pd.MultiIndex.from_product([["num", "den"], PERIODS]), fill_value=0))
    labels = list(g.index)
    s0, s1 = g[("num", "baseline")].to_numpy(float), g[("num", "current")].to_numpy(float)
    n0, n1 = g[("den", "baseline")].to_numpy(float), g[("den", "current")].to_numpy(float)
    N0, N1 = n0.sum(), n1.sum()
    if N0 <= 0 or N1 <= 0:
        raise ValueError(f"{dimension}: a period has no denominator volume (baseline={N0}, current={N1})")

    R0, R1 = s0.sum() / N0, s1.sum() / N1
    delta, rbar = R1 - R0, (R0 + R1) / 2
    c0, c1 = n0 / N0, n1 / N1
    with np.errstate(divide="ignore", invalid="ignore"):
        r0, r1 = s0 / n0, s1 / n1                       # nan where a period has no volume
    r0f, r1f = np.where(n0 > 0, r0, r1), np.where(n1 > 0, r1, r0)   # missing period takes the other's rate
    mix = np.nan_to_num((c1 - c0) * ((r0f + r1f) / 2 - rbar))       # nan only when n0 == n1 == 0
    rate = np.nan_to_num((r1f - r0f) * (c0 + c1) / 2)
    # relative tolerance so INR ratios (avg_ticket_size ~ 1e3) hold too; for rates this is plain 1e-12
    assert abs(mix.sum() + rate.sum() - delta) < 1e-12 * max(1.0, abs(R0), abs(R1)), "rate/mix identity broken"

    counts = bool(np.allclose(np.r_[s0, s1], np.round(np.r_[s0, s1])) and (np.r_[s0, s1] >= 0).all()
                  and (np.r_[s0, s1] <= np.r_[n0, n1]).all())
    segments = []
    for i, label in enumerate(labels):
        both = n0[i] > 0 and n1[i] > 0
        z, p = _ztest(s1[i], n1[i], s0[i], n0[i]) if (counts and both) else (None, None)
        rate0 = float(r0[i]) if n0[i] > 0 else None
        rate1 = float(r1[i]) if n1[i] > 0 else None
        dr = abs(rate1 - rate0) if both else 0.0
        total = float(mix[i] + rate[i])
        segments.append(SegmentEffect(
            dimension=dimension, segment=label, n0=int(round(n0[i])), n1=int(round(n1[i])),
            s0=float(s0[i]), s1=float(s1[i]), share0=float(c0[i]), share1=float(c1[i]),
            rate0=rate0, rate1=rate1, mix_effect=float(mix[i]), rate_effect=float(rate[i]),
            total_effect=total, z=z, p_value=p,
            supported=bool(n0[i] >= MIN_SUPPORT and n1[i] >= MIN_SUPPORT and max(c0[i], c1[i]) >= MIN_SHARE),
            significant=bool(p is not None and p < FDR_Q),
            # practically large: carries >= 5% of the move, and either its rate moved >= 0.3 pp
            # or it is a mix-driven segment (its share moved; its rate need not)
            material=bool(abs(total) >= MIN_CONTRIBUTION * abs(delta) and delta != 0
                          and (dr >= MIN_RATE_DELTA or abs(mix[i]) >= abs(rate[i]))),
        ))
    segments.sort(key=lambda s: -abs(s.total_effect))

    used = (n0 + n1) > 0
    chi2_p = float(chi2_contingency(np.c_[n0[used], n1[used]])[1]) if used.sum() >= 2 else None
    return DimensionDecomposition(
        dimension=dimension, r0=float(R0), r1=float(R1), delta=float(delta),
        mix_total=float(mix.sum()), rate_total=float(rate.sum()), mix_chi2_p=chi2_p,
        score=0.0, simpson_flag=False, segments=segments,
        adtributor=_adtributor(labels, s0, s1, n0, n1),
    )


def _ztest(s1: float, n1: float, s0: float, n0: float) -> tuple[float, float]:
    if s0 + s1 in (0, n0 + n1):          # all-fail or all-succeed in both periods: nothing moved
        return 0.0, 1.0
    z, p = proportions_ztest([s1, s0], [n1, n0])
    return float(z), float(p)


def _judge(dec: DimensionDecomposition) -> DimensionDecomposition:
    """Set simpson_flag and score from each segment's current `significant` flag.

    score = how much of the move this dimension *explains*, as a fraction of Δ (0..2):
        mix part   clip(Σmix / Δ, 0, 1)  composition shifted toward segments whose rate sits on the
                   side of Δ: "nothing got worse, the mix changed".
        rate part  clip(Σ_i w_i * dev_i / |Δ|, 0, 1) over supported segments, w_i = (c0_i + c1_i)/2,
                   dev_i = how far the segment's rate change Δr_i sits beyond the uniform shift Σrate
                   (= the w-weighted mean Δr) in Δ's direction, less 2 standard errors (noise).
                   This is the part of the rate effect concentrated in some segments beyond their volume
                   share. A uniform rate move across all segments scores 0 (the dimension says nothing
                   about it); one narrow segment carrying the whole move scores ~1 - w. So a bank whose
                   rate collapsed (w ~ 0.1) outranks the payment method it runs on (w ~ 0.5), and a pure
                   share shift (mix ~ Δ, flat rates) outranks dimensions where it only shows up as
                   diffuse rate dips.
    """
    d = dec.delta
    worse = [s for s in dec.segments if s.supported and s.significant and s.rate0 is not None
             and s.rate1 is not None and np.sign(s.rate1 - s.rate0) == np.sign(d)]
    dec.simpson_flag = bool(d != 0 and abs(dec.mix_total) >= SIMPSON_MIX_SHARE * abs(d) and not worse)
    if d == 0:
        dec.score = 0.0
        return dec
    excess = 0.0
    for s in dec.segments:
        if not s.supported:          # supported implies both periods have volume, so both rates exist
            continue
        se = 0.0 if s.z is None else np.sqrt(s.rate0 * (1 - s.rate0) / s.n0 + s.rate1 * (1 - s.rate1) / s.n1)
        dev = (s.rate1 - s.rate0 - dec.rate_total) * np.sign(d)
        excess += (s.share0 + s.share1) / 2 * max(0.0, dev - 2 * se) / abs(d)
    dec.score = float(np.clip(dec.mix_total / d, 0, 1) + np.clip(excess, 0, 1))
    return dec


# ---------------------------------------------------------------- Adtributor cross-check
def _adtributor(labels: list[str], s0, s1, n0, n1) -> list[dict]:
    """Explanatory power and surprise per element for a derived (ratio) measure, a = num, b = den,
    predict = baseline, real = current. Adtributor: Bhagwan et al., "Adtributor: Revenue Debugging in
    Advertising Systems", NSDI 2014. Formulas ported from shaido987/riskloc utils/element_scores.py
    (MIT License, Copyright (c) 2024 Marcus Kalander); computed per dimension, so merged_divide = 1."""
    Fa, Fb = s0.sum(), n0.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        ep = np.nan_to_num(((s1 - s0) * Fb - (n1 - n0) * Fa) / (Fb * (Fb + n1 - n0)))
    ep = ep / ep.sum() if ep.sum() else ep
    surprise = _js(s0, s1) + _js(n0, n1)
    rows = [{"segment": lab, "ep": float(e), "surprise": float(su)} for lab, e, su in zip(labels, ep, surprise)]
    return sorted(rows, key=lambda r: -r["surprise"])


def _js(predict, real):
    with np.errstate(divide="ignore", invalid="ignore"):
        p, q = predict / predict.sum(), real / real.sum()
        p_term = np.nan_to_num(p * np.log(2 * p / (p + q)))
        q_term = np.nan_to_num(q * np.log(2 * q / (p + q)))
    return 0.5 * (p_term + q_term)


def _adtributor_pick(dec: DimensionDecomposition) -> tuple[str | None, float]:
    """(most surprising element with EP > TEEP, summed surprise of all such elements)."""
    cands = [a for a in dec.adtributor if a["ep"] > ADTRIBUTOR_TEEP]
    return (cands[0]["segment"] if cands else None), sum(a["surprise"] for a in cands)


# ---------------------------------------------------------------- the report
def explain_change(frames: dict[str, pd.DataFrame], *, metric: str, window: str, baseline: str,
                   drill: dict[tuple[str, str], pd.DataFrame] | None = None) -> DriverReport:
    """Decompose every dimension, apply BH across every segment test in the report (drill cells
    included), rank dimensions by `score` (see _judge: the share of Δ the dimension explains through
    composition plus rate moves concentrated beyond volume share), and drill into caller-chosen pairs.
    top_dimension is None when no dimension explains at least MIN_CONTRIBUTION of the move."""
    if not frames:
        raise ValueError("explain_change needs at least one dimension frame")
    decs = [_decompose(df, dim) for dim, df in frames.items()]

    cell_dims: dict[str, dict[str, str]] = {}
    drill_decs = []
    for (d1, d2), df in (drill or {}).items():
        v1, v2 = (df[d].astype(object).where(df[d].notna(), NONE_LABEL).astype(str) for d in (d1, d2))
        name = f"{d1} × {d2}"
        cell = d1 + "=" + v1 + " · " + d2 + "=" + v2
        cell_dims.update({c: {d1: a, d2: b} for c, a, b in zip(cell, v1, v2)})
        drill_decs.append(_decompose(df.assign(**{name: cell}), name))

    tested = [s for dec in decs + drill_decs for s in dec.segments if s.p_value is not None]
    if tested:
        qs = multipletests([s.p_value for s in tested], method="fdr_bh")[1]
        for s, q in zip(tested, qs):
            s.q_value, s.significant = float(q), bool(q < FDR_Q)
    for dec in decs + drill_decs:
        _judge(dec)

    decs.sort(key=lambda d: -d.score)
    best = decs[0]
    top = best.dimension if best.score >= MIN_CONTRIBUTION else None
    notes = []
    if top is None:
        notes.append("No dimension explains the change: it is spread evenly across every breakdown tried.")
    else:
        seg = best.segments[0].segment
        ad_seg, _ = _adtributor_pick(best)
        ad_dim = max(decs, key=lambda d: _adtributor_pick(d)[1]).dimension
        notes.append(f"Adtributor cross-check {'agrees' if ad_seg == seg else 'disagrees'} on the top segment of "
                     f"{top}: decomposition {seg!r}, Adtributor {ad_seg!r}; Adtributor's most surprising "
                     f"dimension is {ad_dim}{' (same)' if ad_dim == top else ''}.")

    cells = sorted((s for dec in drill_decs for s in dec.segments), key=lambda s: -abs(s.total_effect))
    return DriverReport(
        metric=metric, r0=best.r0, r1=best.r1, delta=best.delta, window=window, baseline=baseline,
        dimensions=decs, top_dimension=top, simpson_flag=bool(top and best.simpson_flag),
        drilldown=[DrillCell(dims=cell_dims[s.segment], effect=s) for s in cells[:DRILL_TOP]],
        notes=notes,
    )


# ---------------------------------------------------------------- evidence
def _keys(texts: dict[str, str]) -> dict[str, str]:
    """Segment label -> placeholder-safe key ([A-Za-z0-9_]+) sanitized from texts[label].
    Deterministic (sorted by label); collisions get _2, _3..."""
    out, used = {}, set()
    for lab in sorted(texts):
        base = re.sub(r"[^A-Za-z0-9]+", "_", texts[lab]).strip("_") or "seg"
        key, i = base, 2
        while key in used:
            key, i = f"{base}_{i}", i + 1
        used.add(key)
        out[lab] = key
    return out


def _segment_evidence(segs: list[SegmentEffect], keys: dict[str, str], rate_fmt: ValueFormat,
                      eff_fmt: ValueFormat) -> tuple[dict, dict, list[dict]]:
    values, formats, table = {}, {}, []
    for s in segs:
        k = keys[s.segment]
        row = {"n0": s.n0, "n1": s.n1, "share0": s.share0, "share1": s.share1, "rate0": s.rate0,
               "rate1": s.rate1, "mix_effect": s.mix_effect, "rate_effect": s.rate_effect,
               "total_effect": s.total_effect}
        fmts = {"n0": "int", "n1": "int", "share0": "pct", "share1": "pct", "rate0": rate_fmt,
                "rate1": rate_fmt, "mix_effect": eff_fmt, "rate_effect": eff_fmt, "total_effect": eff_fmt}
        values.update({f"{k}_{f}": v for f, v in row.items()})
        formats.update({f"{k}_{f}": v for f, v in fmts.items()})
        table.append({"segment": s.segment, "key": k, **row, "z": s.z, "p_value": s.p_value,
                      "q_value": s.q_value, "supported": s.supported, "significant": s.significant,
                      "material": s.material})
    return values, formats, table


def evidence_from_report(report: DriverReport, start_id: int) -> list[Evidence]:
    """Evidence the narrator may cite: the overall comparison, the top-3 dimensions, the drill-down.

    Keys are [A-Za-z0-9_]+. Segment keys are sanitized labels (UPI -> UPI, "(none)" -> none); each
    evidence's `table` maps segment -> key. sql/sql_hashes/tables/filters are left for the caller
    (this function never sees SQL)."""
    cat = load_catalog()
    m = cat.metric(report.metric)
    rate_fmt, eff_fmt = {"percent": ("pct", "pp"), "inr": ("inr", "inr"), "count": ("float", "float")}[m.format]
    dim_label = {d.name: d.label for d in cat.dimensions}
    ev, nid = [], count(start_id)
    common = {"window": report.window, "baseline": report.baseline}

    values = {"r0": report.r0, "r1": report.r1, "delta": report.delta,
              "top_dimension": dim_label.get(report.top_dimension, report.top_dimension or "none"),
              "simpson_flag": "yes" if report.simpson_flag else "no"}
    formats = {"r0": rate_fmt, "r1": rate_fmt, "delta": eff_fmt, "top_dimension": "text", "simpson_flag": "text"}
    if report.dimensions:             # the mix/rate split is per dimension: use the best-ranked one
        best = report.dimensions[0]
        values |= {"mix_total": best.mix_total, "rate_total": best.rate_total,
                   "n0": sum(s.n0 for s in best.segments), "n1": sum(s.n1 for s in best.segments)}
        formats |= {"mix_total": eff_fmt, "rate_total": eff_fmt, "n0": "int", "n1": "int"}
    ev.append(Evidence(id=f"E{next(nid)}", kind="comparison", title=f"{m.label}: current vs baseline",
                       values=values, formats=formats, **common))

    for dec in report.dimensions[:3]:
        keys = _keys({s.segment: s.segment for s in dec.segments})
        values, formats, table = _segment_evidence(dec.segments, keys, rate_fmt, eff_fmt)
        values |= {"delta": dec.delta, "mix_total": dec.mix_total, "rate_total": dec.rate_total,
                   "score": dec.score, "simpson_flag": "yes" if dec.simpson_flag else "no"}
        formats |= {"delta": eff_fmt, "mix_total": eff_fmt, "rate_total": eff_fmt, "score": "float",
                    "simpson_flag": "text"}
        ev.append(Evidence(id=f"E{next(nid)}", kind="decomposition",
                           title=f"{m.label} by {dim_label.get(dec.dimension, dec.dimension)}: mix vs rate",
                           values=values, formats=formats, table=table, row_count=len(table), **common))

    if report.drilldown:
        segs = [c.effect for c in report.drilldown]
        keys = _keys({c.effect.segment: " ".join(c.dims.values()) for c in report.drilldown})
        values, formats, table = _segment_evidence(segs, keys, rate_fmt, eff_fmt)
        for row, c in zip(table, report.drilldown):
            row.update(c.dims)
        ev.append(Evidence(id=f"E{next(nid)}", kind="drilldown", title=f"{m.label}: depth-2 drill-down",
                           values=values, formats=formats, table=table, row_count=len(table), **common))
    return ev
