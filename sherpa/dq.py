"""Data-quality checks for a window: duplicates, ingestion gaps, null issuers, freshness.

Pure pandas in, DQWarning out (docs/CONTRACTS.md §3). Messages are code-generated, so they may carry numbers.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .contracts import DQWarning, TimeWindow
from .drivers import NONE_LABEL

DUP_MIN_EVENTS = 100        # a day x gateway with this many duplicate events ...
DUP_MIN_SHARE = 0.005       # ... or this share of its events is worth a warning
GAP_RATIO = 0.10            # an hour below 10% of its usual volume (7-day median) is a gap candidate
# A run of consecutive candidate hours is reported only if it should have held >= GAP_MIN_EXPECTED attempts:
# one empty night hour that usually sees 3 attempts is noise (Poisson P(0) = 5%), six empty hours that
# usually see 300 are an outage. Seeing <= 10% of 20 expected has Poisson probability < 1e-6.
GAP_MIN_EXPECTED = 20
_SEVERITY = {"error": 0, "warn": 1, "info": 2}


def _d(x: date) -> str:
    return f"{x.day} {x:%b}"


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def run_checks(dq_daily: pd.DataFrame, hourly: pd.DataFrame, *, window: TimeWindow, as_of: date) -> list[DQWarning]:
    """dq_daily: analytics.dq_daily rows for the window.
    hourly: [txn_date, txn_hour, gateway, attempts] covering window.start - 7 days .. window.end."""
    start, end = window.start, window.end
    out: list[DQWarning] = []

    if end > as_of:
        out.append(DQWarning(
            check="freshness", severity="warn",
            message=f"The window ends {_d(end)}, after the latest complete day of data ({_d(as_of)}): "
                    f"{(end - as_of).days} day(s) have no data yet.",
            values={"window_end": end.isoformat(), "as_of": as_of.isoformat(), "days_missing": (end - as_of).days}))

    daily = dq_daily.assign(txn_date=_dates(dq_daily["txn_date"]))
    daily = daily[(daily["txn_date"] >= start) & (daily["txn_date"] <= end)]

    dups = daily.groupby(["txn_date", "gateway"], as_index=False)[["duplicate_events", "raw_events"]].sum()
    for r in dups.itertuples():
        share = r.duplicate_events / r.raw_events if r.raw_events else 0.0
        if r.duplicate_events > 0 and (r.duplicate_events >= DUP_MIN_EVENTS or share >= DUP_MIN_SHARE):
            out.append(DQWarning(
                check="duplicates", severity="warn",
                message=f"{r.gateway} sent {r.duplicate_events:,} duplicate events on {_d(r.txn_date)} "
                        f"({share:.1%} of {r.raw_events:,}); they were removed by deduplication.",
                values={"date": r.txn_date.isoformat(), "gateway": r.gateway,
                        "duplicate_events": int(r.duplicate_events), "raw_events": int(r.raw_events),
                        "share": float(share)}))

    nulls = int(daily["null_issuer_nonwallet"].sum())
    if nulls > 0:
        out.append(DQWarning(
            check="nulls", severity="warn",
            message=f"{nulls:,} non-wallet payments between {_d(start)} and {_d(end)} have no issuer bank; "
                    f"bank breakdowns show them as '{NONE_LABEL}'.",
            values={"null_issuer_nonwallet": nulls}))

    out += _gaps(hourly, start, min(end, as_of))
    return sorted(out, key=lambda w: _SEVERITY[w.severity])


def _gaps(hourly: pd.DataFrame, start: date, end: date) -> list[DQWarning]:
    """Hours in [start, end] whose attempts fall below GAP_RATIO x the median of the same hour and gateway
    over the 7 preceding days; consecutive such hours of a gateway merge into one run, reported as an error
    when the run usually holds >= GAP_MIN_EXPECTED attempts. An empty hour that is usually empty too
    (median 0, small filtered views) may bridge the inside of a run but never starts or ends one, so an
    outage is reported with its full range rather than split or shortened."""
    if hourly.empty or end < start:
        return []
    h = hourly.assign(txn_date=_dates(hourly["txn_date"]))
    first = h["txn_date"].min()          # history before the data starts is unknown, not zero
    days = pd.date_range(min(first, start - timedelta(days=7)), end).date
    grid = pd.MultiIndex.from_product([days, range(24), sorted(h["gateway"].unique())],
                                      names=["txn_date", "txn_hour", "gateway"])
    att = h.groupby(["txn_date", "txn_hour", "gateway"])["attempts"].sum().reindex(grid, fill_value=0).astype(float)

    gaps, out = [], []
    for d in pd.date_range(first, end).date:     # days before the window too, so an earlier outage is known
        hist = [x for x in (d - timedelta(days=k) for k in range(1, 8)) if x >= first]
        if not hist:
            if d >= start:
                out.append(DQWarning(check="missing_data", severity="info", values={"date": d.isoformat()},
                                     message=f"Completeness of {_d(d)} could not be checked: there is no earlier "
                                             f"data to compare it with."))
            continue
        med = att.loc[hist].groupby(level=["txn_hour", "gateway"]).median()
        cur = att.loc[d]
        flagged = ((med > 0) & (cur < GAP_RATIO * med)) | ((med == 0) & (cur == 0))
        hits = [(gw, d, hr, int(cur[(hr, gw)]), float(med[(hr, gw)])) for hr, gw in flagged[flagged].index]
        for gw, _, hr, _, usual in hits:      # an outage must not become its own baseline: later days see
            att.loc[(d, hr, gw)] = usual      # a flagged hour at its usual volume
        if d >= start:
            gaps += hits

    gaps.sort(key=lambda g: (g[0], g[1], g[2]))
    runs: list[list[tuple]] = []
    for g in gaps:
        prev = runs[-1][-1] if runs else None
        if prev and prev[0] == g[0] and _hour_index(g) == _hour_index(prev) + 1:
            runs[-1].append(g)
        else:
            runs.append([g])
    for run in runs:
        while run and run[0][4] == 0:        # usually-empty hours only bridge, never extend, a run
            run = run[1:]
        while run and run[-1][4] == 0:
            run = run[:-1]
        got, usual = sum(g[3] for g in run), sum(g[4] for g in run)
        if usual < GAP_MIN_EXPECTED:
            continue
        gw, (d0, h0), (d1, h1) = run[0][0], run[0][1:3], run[-1][1:3]
        stop = pd.Timestamp(d1) + pd.Timedelta(hours=h1 + 1)
        same_day = stop <= pd.Timestamp(d0 + timedelta(days=1))
        rng = (f"{_d(d0)} {h0:02d}:00–{stop:%H}:00 IST" if same_day
               else f"{_d(d0)} {h0:02d}:00 – {_d(stop.date())} {stop:%H}:00 IST")
        what = "has no data" if got == 0 else f"has almost no data ({got:,} attempts vs ~{usual:,.0f} usual)"
        out.append(DQWarning(
            check="missing_data", severity="error", message=f"{gw} {what} on {rng}.",
            values={"gateway": gw, "start": f"{d0.isoformat()}T{h0:02d}:00", "end": stop.strftime("%Y-%m-%dT%H:%M"),
                    "hours": len(run), "attempts": got, "usual_attempts": round(usual)}))
    return out


def _hour_index(g: tuple) -> int:
    return g[1].toordinal() * 24 + g[2]
