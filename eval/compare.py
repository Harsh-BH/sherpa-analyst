"""Result-set equivalence and the unsupported-number check.

compare() is adapted from defog-ai/sql-eval, eval/eval.py (normalize_table, compare_df, subset_df,
compare_query_results), Copyright Defog, Inc., Apache License 2.0 (https://github.com/defog-ai/sql-eval).
Changes: column types are normalised (Decimal/date/numeric strings), row order is always ignored, a gold
column matches a candidate column by name first and by sorted values second (so extra and renamed candidate
columns are fine), and numbers compare with a tolerance instead of exactly.

Numeric tolerance: equal at 4 significant digits (Databricks Genie's rule) or within relative 1e-2
(Spider 2.0's rule). A candidate column may also be the gold column x100 or /100 (rates written as
percentages), applied to the whole column.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

SCALES = (1.0, 100.0, 0.01)


def _norm_value(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (Decimal, int, float)):
        return float(v)
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if isinstance(v, datetime):        # before date: datetime is a date subclass
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case column names, plain Python values, numeric-looking text as floats, no duplicate rows."""
    out = pd.DataFrame({str(c).strip().lower(): [_norm_value(v) for v in df[c]] for c in df.columns}, dtype=object)
    for c in out.columns:
        vals = [v for v in out[c] if v is not None]
        if vals and all(isinstance(v, str) for v in vals):
            try:
                out[c] = pd.Series([None if v is None else float(v) for v in out[c]], dtype=object)
            except ValueError:
                pass
    return out.loc[~out.astype(str).duplicated()].reset_index(drop=True)


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str) or isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if a == b or abs(a - b) <= 1e-9:
        return True
    return _sig(a, 4) == _sig(b, 4) or abs(a - b) <= 1e-2 * max(abs(a), abs(b))


def _sig(x: float, n: int) -> float:
    return 0.0 if x == 0 else round(x, n - 1 - math.floor(math.log10(abs(x))))


def _key(v):
    """Sort key that survives tolerance: numbers rounded to 3 significant digits, None first."""
    if v is None:
        return (0, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (1, _sig(v, 3))
    return (2, str(v))


def _scaled(col: list, s: float) -> list:
    return [v * s if isinstance(v, float) else v for v in col]


def _column_matches(g: list, c: list, scale: float) -> bool:
    cs = _scaled(c, scale)
    return all(close(x, y) for x, y in zip(sorted(g, key=_key), sorted(cs, key=_key)))


def compare(gold: pd.DataFrame, cand: pd.DataFrame) -> tuple[bool, str]:
    """(equivalent, detail). Every gold column must match one candidate column; rows match as a multiset."""
    g, c = normalize(gold), normalize(cand)
    if g.empty and c.empty:
        return True, "both empty"
    if len(g) != len(c):
        return False, f"rows: gold {len(g)} vs candidate {len(c)}"
    free = list(c.columns)
    mapping: dict[str, tuple[str, float]] = {}
    for col in g.columns:      # by name first, then by sorted values (defog subset_df)
        order = [col] + [x for x in free if x != col] if col in free else free
        hit = next(((x, s) for x in order for s in SCALES if _column_matches(list(g[col]), list(c[x]), s)), None)
        if hit is None:
            return False, f"no candidate column matches gold column {col!r}"
        mapping[col] = hit
        free.remove(hit[0])
    cand_m = pd.DataFrame({col: _scaled(list(c[x]), s) for col, (x, s) in mapping.items()}, dtype=object)
    cols = list(g.columns)
    g_rows = sorted(map(tuple, g[cols].itertuples(index=False)), key=lambda r: tuple(map(_key, r)))
    c_rows = sorted(map(tuple, cand_m[cols].itertuples(index=False)), key=lambda r: tuple(map(_key, r)))
    for i, (a, b) in enumerate(zip(g_rows, c_rows)):
        if not all(close(x, y) for x, y in zip(a, b)):
            return False, f"row {i}: gold {a} vs candidate {b}"
    renamed = {k: v[0] for k, v in mapping.items() if v[0] != k or v[1] != 1.0}
    return True, f"{len(g)} rows match" + (f" (columns mapped {renamed})" if renamed else "")


# ---------------------------------------------------------------- unsupported numbers in free text
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_NOT_DATA = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}(?:[ T]\d{{2}}:\d{{2}})?\b"            # ISO dates / timestamps
    rf"|\b\d{{1,2}}:\d{{2}}\b"                                         # clock times
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?[ -]+(?:{_MONTHS})[a-z]*\.?(?:,? \d{{4}})?"   # 19 Nov 2026
    rf"|\b(?:{_MONTHS})[a-z]*\.? \d{{1,2}}(?:st|nd|rd|th)?\b(?:,? \d{{4}})?"     # Nov 19, 2026
    rf"|\b(?:19|20)\d{{2}}\b"                                          # years
    rf"|\b[A-Z]+_?\d+\b"                                               # ids: PG_A2, M01362
    rf"|\bE\d+\.\w+",                                                  # placeholders
    re.IGNORECASE)
_NUM = re.compile(r"(?<![\w.])[-+−]?(?:₹\s?)?(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?\s*(%|pp|percentage points?|cr(?:ore)?|l(?:akh)?|k|m(?:n|illion)?|bn)?(?![\w])",
                  re.IGNORECASE)
_MULT = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9}


def numerals(text: str) -> list[tuple[str, list[float]]]:
    """Numbers in free text (dates, times, years and ids removed) as (as written, readings it may mean)."""
    out = []
    for m in _NUM.finditer(_NOT_DATA.sub(" ", text)):
        x = float(m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else ""))
        unit = (m.group(3) or "").lower()
        if unit in ("%", "pp") or unit.startswith("percentage"):
            readings = [x / 100, x]           # 91.7% may be 0.917 or the value 91.7
        elif unit:
            readings = [x * _MULT[unit if unit in _MULT else unit[0]]]
        else:
            readings = [x]
        out.append((m.group(0).strip(), readings))
    return out


def unsupported_numbers(text: str, values: list, allowed_text: str = "") -> list[str]:
    """Numerals in `text` that match no value in `values` at 3 significant digits (sign ignored).
    Numbers that also appear in `allowed_text` (the question) are not data claims."""
    nums = [abs(float(v)) for v in values if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
            and not (isinstance(v, float) and math.isnan(v))]
    allowed = {r for _, rs in numerals(allowed_text) for r in rs}
    bad = []
    for written, readings in numerals(text):
        if any(r in allowed for r in readings):
            continue
        if not any(_sig(r, 3) == _sig(n, 3) or abs(r - n) <= 5e-3 * max(r, n) for r in readings for n in nums):
            bad.append(written)
    return bad
