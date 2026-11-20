from datetime import date, timedelta

import pandas as pd

from sherpa.contracts import TimeWindow
from sherpa.dq import run_checks

AS_OF = date(2026, 11, 19)
WINDOW = TimeWindow(start=date(2026, 11, 13), end=AS_OF, label="last 7 days")
GATEWAYS = ["PG_A", "PG_B", "PG_C"]
SHAPE = [40, 25, 20, 20, 25, 60, 150, 300, 450, 550, 600, 620, 640, 600, 580, 560, 560, 580, 620, 650, 600, 450, 250, 100]


def clean_hourly() -> pd.DataFrame:
    days = pd.date_range(WINDOW.start - timedelta(days=7), WINDOW.end).date
    return pd.DataFrame([(d, h, g, SHAPE[h] + (i % 5)) for i, d in enumerate(days) for h in range(24)
                         for g in GATEWAYS], columns=["txn_date", "txn_hour", "gateway", "attempts"])


def clean_daily() -> pd.DataFrame:
    days = pd.date_range(WINDOW.start, WINDOW.end).date
    return pd.DataFrame([(d, r, g, 2_003, 2_000, 3, 0, 40) for d in days for r in ["North", "South"] for g in GATEWAYS],
                        columns=["txn_date", "region", "gateway", "raw_events", "distinct_txns",
                                 "duplicate_events", "null_issuer_nonwallet", "max_ingest_lag_s"])


def test_clean_window_has_no_warnings():
    assert run_checks(clean_daily(), clean_hourly(), window=WINDOW, as_of=AS_OF) == []


def test_duplicates_warn_per_day_and_gateway():
    daily = clean_daily()
    hit = (daily["txn_date"] == date(2026, 11, 14)) & (daily["gateway"] == "PG_B")
    daily.loc[hit, "duplicate_events"] = 602          # 1,204 across two regions
    daily.loc[hit, "raw_events"] = 2_602
    [w] = run_checks(daily, clean_hourly(), window=WINDOW, as_of=AS_OF)
    assert (w.check, w.severity) == ("duplicates", "warn")
    assert "PG_B" in w.message and "14 Nov" in w.message and "1,204" in w.message
    assert "removed by deduplication" in w.message
    assert w.values["duplicate_events"] == 1_204


def test_duplicate_share_threshold():
    daily = clean_daily()
    hit = (daily["txn_date"] == date(2026, 11, 15)) & (daily["gateway"] == "PG_A")
    daily.loc[hit, "duplicate_events"] = 15           # 30 of 4,006 = 0.75% (< 100 events, > 0.5%)
    [w] = run_checks(daily, clean_hourly(), window=WINDOW, as_of=AS_OF)
    assert w.check == "duplicates" and w.values["gateway"] == "PG_A"


def test_missing_hours_merge_into_one_error():
    hourly = clean_hourly()
    gap = (hourly["txn_date"] == date(2026, 11, 16)) & (hourly["gateway"] == "PG_C") & hourly["txn_hour"].between(2, 7)
    hourly = hourly[~gap]                             # no rows at all for those hours
    [w] = run_checks(clean_daily(), hourly, window=WINDOW, as_of=AS_OF)
    assert (w.check, w.severity) == ("missing_data", "error")
    assert w.message == "PG_C has no data on 16 Nov 02:00–08:00 IST."
    assert w.values["hours"] == 6 and w.values["attempts"] == 0


def test_partial_gap_across_midnight():
    hourly = clean_hourly()
    d = hourly["txn_date"]
    late = (d == date(2026, 11, 17)) & hourly["txn_hour"].isin([22, 23])
    early = (d == date(2026, 11, 18)) & hourly["txn_hour"].isin([0])
    hit = (late | early) & (hourly["gateway"] == "PG_A")
    hourly.loc[hit, "attempts"] = 2
    [w] = run_checks(clean_daily(), hourly, window=WINDOW, as_of=AS_OF)
    assert w.message.startswith("PG_A has almost no data (6 attempts")
    assert "17 Nov 22:00 – 18 Nov 01:00 IST" in w.message


def test_nulls_and_freshness():
    daily = clean_daily()
    daily.loc[0, "null_issuer_nonwallet"] = 37
    late = TimeWindow(start=WINDOW.start, end=AS_OF + timedelta(days=2))
    ws = run_checks(daily, clean_hourly(), window=late, as_of=AS_OF)
    assert [w.check for w in ws] == ["freshness", "nulls"]      # days after as_of are not reported as gaps
    assert ws[0].values["days_missing"] == 2 and "37 non-wallet" in ws[1].message


def test_low_volume_gap_is_one_run_and_quiet_hours_are_not_gaps():
    # a filtered view: night hours usually see 2-7 attempts each, too few to judge one hour alone
    hourly = clean_hourly().assign(attempts=lambda d: [max(1, SHAPE[h] // 8) + (i % 2)
                                                       for i, h in enumerate(d["txn_hour"])])
    d = hourly["txn_date"]
    hourly.loc[(d == date(2026, 11, 16)) & (hourly["gateway"] == "PG_C") & hourly["txn_hour"].between(2, 7), "attempts"] = 0
    hourly.loc[(d == date(2026, 11, 18)) & (hourly["gateway"] == "PG_A") & (hourly["txn_hour"] == 3), "attempts"] = 0
    [w] = run_checks(clean_daily(), hourly, window=WINDOW, as_of=AS_OF)
    assert w.message == "PG_C has no data on 16 Nov 02:00–08:00 IST."
    assert w.values["hours"] == 6
