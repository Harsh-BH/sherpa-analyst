"""Executor: guarded SQL runs as the persona's own DB role, in a read-only transaction that is always
rolled back, under a statement timeout and an EXPLAIN cost gate. Postgres (grants + RLS) is the backstop
even if the guard had a bug: a persona's role cannot read raw.*, app.* or another region's rows.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import replace

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader

from .config import MAX_ROWS, STATEMENT_TIMEOUT_MS, load_access, settings
from .contracts import QueryRejected, QueryResult
from .guard import check_sql

# EXPLAIN cost ceiling, gated on the max Total Cost over the whole plan tree (a root Limit pro-rates its
# child, R4). Calibrated on seed 42 (1.56M transactions), 2026-11-21:   sherpa_head   sherpa_rm_south   runtime
#   14-day two-period success_rate by issuer_bank (brief)                   52,895            45,808
#   heaviest catalog query: 60-day gmv by merchant                          54,474            44,475    0.3 s
#   LLM-style: top 10 transactions by amount (sort node)                   205,166            92,613    0.3 s
#   LLM-style: count(DISTINCT merchant_id)                                 241,770           105,793    1.1 s
#   self-join on merchant_id, count(*)                                  43,285,420         6,313,825    >20 s
#   self-join on merchant_id returning rows (root Limit says ~51k)     290,052,926        56,450,768    >5 s
# 1M: 18x headroom over catalog queries, 4x over the heaviest legit LLM query, rejects the cheapest
# runaway by 6x. (Was 200k when the gate read only the root node.)
MAX_COST = 1_000_000.0

# Bytes of cell data one query may bring into the app (R2: a window string_agg makes every row megabytes).
MAX_RESULT_BYTES = 50 * 2**20

_CACHE: OrderedDict[tuple[str, str, str, int], QueryResult] = OrderedDict()
_CACHE_SIZE = 256
_LOCK = threading.Lock()   # ponytail: one global lock around a tiny dict, per-key locks only if contention shows


def _role(persona: str, sql: str | None = None) -> str:
    try:
        return load_access().persona(persona).db_role
    except KeyError:
        raise QueryRejected("access", f"Unknown persona {persona!r}.", sql) from None


def _connect(role: str) -> psycopg.Connection:
    # ponytail: one connection per query, a pool if connect latency starts to matter
    conn = psycopg.connect(settings().dsn(role), connect_timeout=5)
    conn.adapters.register_loader("numeric", FloatLoader)   # SUM(bigint) is numeric: return floats, not Decimal
    conn.read_only = True                                    # every transaction starts with BEGIN READ ONLY
    return conn


@contextmanager
def _db_errors(sql: str | None, timeout_ms: int):
    try:
        yield
    except QueryRejected:
        raise
    except psycopg.errors.QueryCanceled:
        raise QueryRejected("timeout", f"The query ran longer than {timeout_ms:,} ms and was cancelled. "
                                       "Narrow the window or add filters.", sql) from None
    except psycopg.errors.InsufficientPrivilege as e:
        raise QueryRejected("access", f"The database refused access: {e.diag.message_primary}.", sql) from None
    except psycopg.Error as e:
        msg = e.diag.message_primary if getattr(e, "diag", None) else None
        # never echo str(e): connection errors carry host, port and user
        raise QueryRejected("db", f"Database error: {msg}." if msg else "The database is unavailable.", sql) from None


def _max_cost(plan: dict) -> float:
    """Highest Total Cost anywhere in the plan tree: a root Limit pro-rates its child's cost (R4)."""
    return max([plan["Total Cost"], *(_max_cost(c) for c in plan.get("Plans", []))])


def _size(v) -> int:
    if isinstance(v, (str, bytes)):
        return len(v)
    if isinstance(v, (list, tuple)):
        return 8 + sum(_size(x) for x in v)
    return 8


def _fetch(cur: psycopg.Cursor, sql: str, max_rows: int) -> list[tuple]:
    """Up to max_rows + 1 rows, streamed one at a time (libpq single-row mode), within MAX_RESULT_BYTES (R2).
    stream() keeps parallel plans; a DECLAREd server-side cursor never runs in parallel (2x slower here)."""
    rows: list[tuple] = []
    used = 0
    gen = cur.stream(sql)
    try:
        for row in gen:
            rows.append(row)
            used += sum(_size(v) for v in row)
            if used > MAX_RESULT_BYTES:
                raise QueryRejected("cost", f"The result is too large (over {MAX_RESULT_BYTES // 2**20} MB). "
                                            "Select fewer or narrower columns, or aggregate.", sql)
            if len(rows) > max_rows:
                break
    finally:
        gen.close()   # an early exit cancels the rest of the result
    return rows


def _columns(conn: psycopg.Connection, cur: psycopg.Cursor, sql: str) -> list[str]:
    """Result column names. An empty stream() leaves cursor.description unset, so then ask the server to
    describe the statement (prepare + describe the unnamed statement; nothing executes)."""
    if cur.description:
        return [d.name for d in cur.description]
    enc = conn.info.encoding
    res = conn.pgconn.prepare(b"", sql.encode(enc))
    if res.status == psycopg.pq.ExecStatus.COMMAND_OK:
        res = conn.pgconn.describe_prepared(b"")
    if res.status != psycopg.pq.ExecStatus.COMMAND_OK:
        raise psycopg.DatabaseError((res.error_message or b"describe failed").decode(enc, "replace"))
    return [res.fname(i).decode(enc) for i in range(res.nfields)]


def _version(conn: psycopg.Connection) -> dict:
    row = conn.cursor(row_factory=dict_row).execute(
        "SELECT version, seed, data_start, as_of FROM analytics.data_version").fetchone()
    if row is None:
        raise QueryRejected("db", "analytics.data_version is empty: the database has not been seeded.")
    return row


def data_version(persona: str) -> dict:
    """{"version", "seed", "data_start", "as_of"} (dates as date), read as the persona's role."""
    with _db_errors(None, STATEMENT_TIMEOUT_MS):
        conn = _connect(_role(persona))
        try:
            v = _version(conn)
            conn.rollback()
            return v
        finally:
            conn.close()


def run_query(sql: str, persona: str, *, max_rows: int = MAX_ROWS, timeout_ms: int = STATEMENT_TIMEOUT_MS,
              max_cost: float | None = None, use_cache: bool = True) -> QueryResult:
    """guard -> connect as persona -> BEGIN READ ONLY -> cache lookup (keyed on data_version) ->
    SET LOCAL statement_timeout -> EXPLAIN cost gate -> execute (fetch max_rows + 1) -> ROLLBACK.
    Raises QueryRejected(stage=parse|policy|cost|timeout|access|db). max_cost None means MAX_COST."""
    g = check_sql(sql, max_rows=max_rows)
    return _run(g.sql, persona, max_rows=max_rows, timeout_ms=timeout_ms, max_cost=max_cost,
                use_cache=use_cache, tables=g.tables)


def _run(sql: str, persona: str, *, max_rows: int = MAX_ROWS, timeout_ms: int = STATEMENT_TIMEOUT_MS,
         max_cost: float | None = None, use_cache: bool = True, tables: list[str] = []) -> QueryResult:
    """Execution without the guard. Only run_query (after check_sql) and the backstop tests call this."""
    t0 = time.perf_counter()
    limit = MAX_COST if max_cost is None else max_cost
    with _db_errors(sql, timeout_ms):
        conn = _connect(_role(persona, sql))
        try:
            key = (sql, persona, _version(conn)["version"], max_rows)   # max_rows decides `truncated` (R6)
            if use_cache:
                with _LOCK:
                    hit = _CACHE.get(key)
                    if hit:
                        _CACHE.move_to_end(key)
                if hit:
                    conn.rollback()
                    return replace(hit, df=hit.df.copy(), cached=True,
                                   elapsed_ms=round((time.perf_counter() - t0) * 1000))
            conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            cost = float(_max_cost(conn.execute(f"EXPLAIN (FORMAT JSON) {sql}").fetchone()[0][0]["Plan"]))
            if cost > limit:
                raise QueryRejected("cost", f"The query is too expensive to run (estimated cost {cost:,.0f}, "
                                            f"limit {limit:,.0f}). Narrow the window or add filters.", sql)
            cur = conn.cursor()
            rows = _fetch(cur, sql, max_rows)
            cols = _columns(conn, cur, sql)
            conn.rollback()
        finally:
            conn.close()
    truncated = len(rows) > max_rows
    df = pd.DataFrame(rows[:max_rows], columns=cols)
    res = QueryResult(df=df, sql=sql, sql_hash=hashlib.sha256(sql.encode()).hexdigest()[:12], persona=persona,
                      row_count=len(df), truncated=truncated, elapsed_ms=round((time.perf_counter() - t0) * 1000),
                      est_cost=cost, cached=False, tables=list(tables))
    if use_cache:
        # ponytail: in-process LRU of copies, invalidated by data_version; shared cache (redis) if multi-process
        with _LOCK:
            _CACHE[key] = replace(res, df=df.copy())
            while len(_CACHE) > _CACHE_SIZE:
                _CACHE.popitem(last=False)
    return res
