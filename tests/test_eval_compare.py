from datetime import date
from decimal import Decimal

import pandas as pd

from eval.compare import compare, numerals, unsupported_numbers

GOLD = pd.DataFrame({"segment": ["UPI", "CARD", "NETBANKING"], "value": [0.8868, 0.9612, 0.9201],
                     "den": [70_000, 60_000, 15_000]})


def test_row_order_extra_columns_and_types():
    cand = pd.DataFrame({"key": ["NETBANKING", "UPI", "CARD"], "segment": ["NETBANKING", "UPI", "CARD"],
                         "value": [Decimal("0.92013"), Decimal("0.88676"), Decimal("0.96119")],
                         "den": [15_000.0, 70_000.0, 60_000.0], "extra": [1, 2, 3]})
    ok, detail = compare(GOLD, cand)
    assert ok, detail


def test_renamed_columns_match_by_value_and_percent_scale():
    cand = pd.DataFrame({"Payment_Method": ["CARD", "UPI", "NETBANKING"], "success_pct": [96.12, 88.68, 92.01],
                         "attempts": [60_000, 70_000, 15_000]})
    ok, detail = compare(GOLD, cand)
    assert ok and "mapped" in detail, detail


def test_numeric_tolerance():
    assert compare(pd.DataFrame({"v": [123456.0]}), pd.DataFrame({"v": [123460.0]}))[0]    # 4 significant digits
    assert compare(pd.DataFrame({"v": [100.0]}), pd.DataFrame({"v": [100.9]}))[0]          # within 1%
    assert not compare(pd.DataFrame({"v": [100.0]}), pd.DataFrame({"v": [102.0]}))[0]
    assert compare(pd.DataFrame({"v": [0.0]}), pd.DataFrame({"v": [1e-12]}))[0]


def test_mismatches_are_explained():
    ok, detail = compare(GOLD, GOLD.head(2))
    assert not ok and detail == "rows: gold 3 vs candidate 2"
    wrong = GOLD.assign(value=[0.8868, 0.9612, 0.95])
    ok, detail = compare(GOLD, wrong)
    assert not ok and "value" in detail
    ok, detail = compare(GOLD, GOLD.assign(segment=["UPI", "CARD", "WALLET"]))
    assert not ok and "segment" in detail


def test_dates_nulls_and_empty():
    g = pd.DataFrame({"bucket": [date(2026, 11, 18), date(2026, 11, 19)], "value": [0.9, None]})
    c = pd.DataFrame({"bucket": ["2026-11-19", "2026-11-18"], "value": [float("nan"), 0.9]})
    assert compare(g, c)[0]
    assert compare(pd.DataFrame({"a": []}), pd.DataFrame())[0]


def test_numerals_skip_dates_times_ids():
    text = "On 16 Nov 2026 PG_C had no data 02:00–08:00 IST; SR fell 1.10 pp to 91.7% on ₹12.35 Cr and 1,233 events."
    got = [w for w, _ in numerals(text)]
    assert got == ["1.10 pp", "91.7%", "₹12.35 Cr", "1,233"]


def test_unsupported_numbers():
    values = [0.9167, -0.011, 123_456_789, 1233]
    text = "SR fell 1.10 pp to 91.7% over the last 7 days; GMV ₹12.35 Cr; 1,233 duplicates; 42% were UPI."
    assert unsupported_numbers(text, values, allowed_text="last 7 days") == ["42%"]


def test_numbers_match_at_their_written_precision():
    # 0.0087 renders as "0.9%" and -0.00673 as "-0.67 pp": correct roundings, fewer than 3 significant digits
    assert unsupported_numbers("TD was 0.9%; SR fell -0.67 pp", [0.0087, -0.00673]) == []
    assert unsupported_numbers("TD was 1.2%", [0.0087]) == ["1.2%"]


def test_ranges_share_their_unit_and_month_day_dates_are_skipped():
    assert numerals("Nov 13–19 vs 6–12 Nov 2026") == []
    assert [w for w, _ in numerals("volume 23–27K per day, TD 0.67–0.76%, data ends 11-19")] == \
        ["23K", "27K", "0.67%", "0.76%"]
    assert unsupported_numbers("about 23–27K a day", [23_419, 26_800]) == []
