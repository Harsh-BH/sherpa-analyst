"""SQL guard: every statement (compiled or LLM-written) passes here before it reaches Postgres.

check_sql parses with sqlglot, refuses anything that is not one read-only SELECT over the exposed
analytics.* tables and columns, enforces a LIMIT, and returns SQL regenerated from the checked tree.
The regenerated SQL (every table schema-qualified, comments stripped) is what executes.
Refusals are plain English and name the offending thing. The DB roles (db/roles.py) are the backstop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from .config import MAX_ROWS, load_access
from .contracts import QueryRejected

SCHEMA = "analytics"
DIALECT = "postgres"

# Statement / clause types that write, lock, or change session state. Root and CTE checks already
# allow only SELECTs; this walk also catches them nested anywhere in the tree.
_FORBIDDEN = {
    exp.Insert: "INSERT", exp.Update: "UPDATE", exp.Delete: "DELETE", exp.Merge: "MERGE",
    exp.Create: "CREATE", exp.Drop: "DROP", exp.Alter: "ALTER", exp.TruncateTable: "TRUNCATE",
    exp.Copy: "COPY", exp.Grant: "GRANT", exp.Revoke: "REVOKE", exp.Comment: "COMMENT ON",
    exp.Set: "SET", exp.SetItem: "SET", exp.Transaction: "BEGIN", exp.Commit: "COMMIT",
    exp.Rollback: "ROLLBACK", exp.Into: "SELECT ... INTO (it creates a table)",
    exp.Lock: "FOR UPDATE / FOR SHARE (a row lock)", exp.Analyze: "ANALYZE", exp.Use: "USE",
    exp.Pragma: "PRAGMA", exp.Kill: "KILL", exp.LoadData: "LOAD DATA", exp.Cache: "CACHE",
    exp.Uncache: "UNCACHE", exp.Refresh: "REFRESH", exp.Declare: "DECLARE", exp.Describe: "DESCRIBE",
    exp.Show: "SHOW", exp.Summarize: "SUMMARIZE", exp.Attach: "ATTACH", exp.Detach: "DETACH",
    exp.Execute: "EXECUTE", exp.Export: "EXPORT", exp.Install: "INSTALL", exp.Command: "This command",
}

# Functions by sqlglot name: typed nodes use sql_name() (DATE_TRUNC parses as TIMESTAMP_TRUNC,
# STRING_AGG as GROUP_CONCAT, ...), anonymous ones their own name. Anything else is refused,
# which covers pg_*, lo_*, dblink*, txid_*, set_config, current_setting, nextval, ...
ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "count", "sum", "avg", "min", "max", "stddev", "stddev_samp", "stddev_pop", "variance",
    "variance_pop", "percentile_cont", "percentile_disc", "logical_and", "logical_or", "corr",
    "group_concat", "string_agg", "array_agg",
    # window
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # conditional, casts
    "case", "if", "coalesce", "nullif", "greatest", "least", "cast", "exists",
    # math
    "abs", "round", "ceil", "floor", "sqrt", "ln", "log", "exp", "power", "sign", "trunc",
    # date/time
    "timestamp_trunc", "date_trunc", "extract", "date", "current_date", "time_to_str", "str_to_date",
    "make_date", "age",
    # string
    "lower", "upper", "length", "substring", "concat", "trim", "initcap", "left", "right", "replace",
    "str_position", "split_part",
})

_T = exp.DataType.Type
ALLOWED_CAST_TYPES = frozenset({
    _T.TEXT, _T.VARCHAR, _T.CHAR, _T.SMALLINT, _T.INT, _T.BIGINT, _T.DECIMAL, _T.DOUBLE, _T.FLOAT,
    _T.BOOLEAN, _T.DATE, _T.TIMESTAMP, _T.TIMESTAMPTZ, _T.INTERVAL,
})


@dataclass
class GuardResult:
    sql: str            # regenerated SQL (comments stripped, LIMIT enforced): this is what runs
    tables: list[str]   # analytics tables referenced (unqualified names)


@lru_cache(maxsize=1)
def _schema() -> dict:
    # qualify only needs names; the type is never used for resolution.
    return {SCHEMA: {t: {c: "unknown" for c in cols} for t, cols in load_access().exposed_tables.items()}}


def _reject(stage: str, reason: str, sql: str) -> QueryRejected:
    return QueryRejected(stage, reason, sql)


def _func_name(node: exp.Func) -> str:
    if isinstance(node, (exp.Anonymous, exp.AnonymousAggFunc)):
        return str(node.this).lower()
    return node.sql_name().lower()


def _table_name(t: exp.Table) -> str:
    return ".".join(p for p in (t.catalog, t.db, t.name) if p)


def check_sql(sql: str, *, max_rows: int = MAX_ROWS) -> GuardResult:
    """Raises QueryRejected(stage="parse"|"policy"); returns the SQL that may execute."""
    try:
        result = _check(sql, max_rows)
        _check(result.sql, max_rows)   # the regenerated SQL must survive the same checks (round-trip)
    except RecursionError:             # sqlglot recurses per nesting level (R5)
        raise _reject("parse", "The SQL is nested too deeply.", sql) from None
    return result


def _check(sql: str, max_rows: int) -> GuardResult:
    # ---- parse: exactly one statement (parse(), not parse_one(), so a second statement can't hide)
    try:
        stmts = [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]
    except ParseError as e:
        err = e.errors[0] if e.errors else {}
        where = f" near '{err.get('highlight')}'" if err.get("highlight") else ""
        raise _reject("parse", f"The SQL could not be parsed{where}: {err.get('description', 'syntax error')}.", sql) from None
    except SqlglotError as e:
        raise _reject("parse", f"The SQL could not be parsed: {e}.", sql) from None
    if not stmts:
        raise _reject("parse", "No SQL statement was found.", sql)
    if len(stmts) > 1:
        raise _reject("parse", f"Only one statement is allowed (found {len(stmts)}).", sql)
    tree = stmts[0]

    # ---- root: SELECT or a set operation
    if isinstance(tree, exp.Command):
        raise _reject("policy", f"{str(tree.this).upper()} statements are not allowed; only SELECT queries can run.", sql)
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        kind = sqlglot.tokenize(sql, read=DIALECT)[0].text.upper()
        raise _reject("policy", f"{kind} statements are not allowed; only SELECT queries can run.", sql)

    # ---- CTEs: bodies must be SELECTs, no recursion, no names that could shadow pg_catalog
    for cte in tree.find_all(exp.CTE):
        if not isinstance(cte.this, (exp.Select, exp.SetOperation)):
            raise _reject("policy", f"CTE {cte.alias} must be a SELECT (data-modifying CTEs are not allowed).", sql)
        if cte.alias.lower().startswith("pg_"):
            raise _reject("policy", f"CTE name {cte.alias} is reserved (names starting with pg_ are not allowed).", sql)
    for w in tree.find_all(exp.With):
        if w.args.get("recursive"):
            raise _reject("policy", "Recursive CTEs are not allowed (they can run without bound).", sql)

    # ---- nodes that write, lock or change session state, anywhere in the tree
    for node in tree.walk():
        kind = next((k for cls, k in _FORBIDDEN.items() if isinstance(node, cls)), None)
        if kind:
            raise _reject("policy", f"{kind} is not allowed; only read-only SELECT queries can run.", sql)

    # ---- functions and casts
    for node in tree.find_all(exp.Func):
        if isinstance(node, exp.Connector):   # AND / OR are Func subclasses in sqlglot
            continue
        name = _func_name(node)
        if isinstance(node.parent, exp.Dot):
            raise _reject("policy", f"Schema-qualified function {node.parent.sql(DIALECT)} is not allowed.", sql)
        if name not in ALLOWED_FUNCTIONS:
            shown = name if isinstance(node, exp.Anonymous) else node.sql(DIALECT).split("(")[0].lower()
            raise _reject("policy", f"Function {shown} is not allowed.", sql)
    # Postgres field selection (expr).name calls name(expr) for any function name, bypassing the allowlist (R1).
    # Qualified columns (analytics.banks.bank_id) parse as Column, never Dot.
    dot = next(tree.find_all(exp.Dot), None)
    if dot is not None:
        raise _reject("policy", f"Field selection {dot.sql(DIALECT)} is not allowed (write name(expr) instead).", sql)
    for dt in tree.find_all(exp.DataType):
        if dt.this not in ALLOWED_CAST_TYPES:
            raise _reject("policy", f"Cast to type {dt.sql(DIALECT)} is not allowed.", sql)

    # ---- tables: explicit schemas first, for a clear message
    exposed = load_access().exposed_tables
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            raise _reject("policy", "Table functions are not allowed in FROM.", sql)
        if t.catalog or (t.db and t.db.lower() != SCHEMA):
            raise _reject("policy", f"Table {_table_name(t)} is outside the analytics schema.", sql)

    # normalise identifiers and pin every non-CTE table to analytics (scope-aware), then re-check
    try:
        tree = qualify(tree, db=SCHEMA, dialect=DIALECT, qualify_columns=False,
                       validate_qualify_columns=False, quote_identifiers=False)
    except OptimizeError as e:
        raise _reject("policy", f"The query could not be resolved: {e}.", sql) from None
    cte_names = {c.alias for c in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for t in tree.find_all(exp.Table):
        if not t.db and t.name in cte_names:
            continue                                   # a CTE reference
        if t.catalog or t.db != SCHEMA:
            raise _reject("policy", f"Table {_table_name(t)} is outside the analytics schema.", sql)
        if t.name not in exposed:
            raise _reject("policy", f"Table {t.name} is not available (visible tables: {', '.join(sorted(exposed))}).", sql)
        tables.add(t.name)

    # ---- columns: qualify against the allowlist; SELECT * expands to allowed columns only
    try:
        tree = qualify(tree, schema=_schema(), db=SCHEMA, dialect=DIALECT,
                       validate_qualify_columns=True, identify=False)
    except OptimizeError as e:
        m = re.search(r"Column '([^']+)'|Unknown column: (\S+)", str(e))
        if m:
            col = (m.group(1) or m.group(2)).strip('"')
            raise _reject("policy", f"Column {col} does not exist or is not visible.", sql) from None
        raise _reject("policy", f"The query could not be resolved: {str(e).split('. Line')[0]}.", sql) from None

    # ---- LIMIT on the outermost query (FETCH ... WITH TIES / PERCENT can exceed n rows: treat as unlimited, R3)
    lim = tree.args.get("limit")
    n = lim.args.get("count") if isinstance(lim, exp.Fetch) else lim.expression if lim else None
    opts = lim.args.get("limit_options") if isinstance(lim, exp.Fetch) else None
    if opts and (opts.args.get("with_ties") or opts.args.get("percent")):
        n = None
    if not (isinstance(n, exp.Literal) and n.is_int and int(n.name) <= max_rows):
        tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows + 1)))

    return GuardResult(sql=tree.sql(dialect=DIALECT, comments=False), tables=sorted(tables))
