# Brief: sql agent (SQL safety, compiler, executor, run log)

You build everything between a plan and a DataFrame. It must be impossible for model-written SQL to
write, escalate, leave `analytics.*` or run away, and every refusal must say why in plain words.

**You own:** `sherpa/guard.py`, `sherpa/compiler.py`, `sherpa/db.py`, `sherpa/runs.py`,
`tests/test_guard.py`, `tests/test_compiler.py`, `tests/test_db.py`, `tests/test_runs.py`.
Signatures: docs/CONTRACTS.md §2. Types: `sherpa/contracts.py`.

Q1 and Q2 are pure (no DB), so start now. Q3–Q5 need the data agent's roles and seed. Write the code
first, and run the `db` tests once `$COORD/data.status` shows the DB is seeded (`uv run pytest -m db tests/test_db.py`).

## Tasks

**Q1: `guard.check_sql`.** Use sqlglot, and check the installed version's API (`uv run python -c "import sqlglot; print(sqlglot.__version__)"`).
- **Statement count:** `sqlglot.parse(sql, dialect="postgres")` must yield exactly one non-None statement. Do not use `parse_one`, which in some versions silently keeps only the first statement.
- **Root node:** must be a `Select` or a set operation (Union/Intersect/Except). A CTE (`WITH`) is allowed only if every CTE body is itself a SELECT, so data-modifying CTEs are rejected.
- **Forbidden nodes anywhere:** Insert, Update, Delete, Merge, Create, Drop, Alter, Command (covers COPY/DO/CALL/VACUUM/etc.), Set, Transaction/Commit/Rollback, Into (`SELECT ... INTO`), Lock (`FOR UPDATE/SHARE`), and anything else your reading of sqlglot's expression types shows can write or change session state.
- **Function allowlist:** aggregates, math, date/time, conditional and string functions you actually need. Reject `exp.Anonymous` functions unless they are allowlisted by name. `set_config`, `current_setting`, `pg_sleep`, anything named `pg_*`, `lo_*`, `dblink*` and `txid_*` must all fail.
- **Tables:** every table must resolve to `analytics.<t>` with `t` in `load_access().exposed_tables` (unqualified names resolve to `analytics`). CTE names are fine. Reject `raw.*`, `app.*`, `pg_catalog`, `information_schema` and any other schema.
- **Columns:** run `sqlglot.optimizer.qualify.qualify(..., schema={"analytics": {...allowed columns...}}, validate_qualify_columns=True)` as the column allowlist. An unknown or forbidden column is rejected with its name. `SELECT *` expands only to allowed columns.
- **LIMIT:** if the outermost query has no LIMIT or exceeds `max_rows`, set `LIMIT max_rows + 1` (the executor uses the extra row to detect truncation).
- **Output:** return regenerated SQL (`.sql(dialect="postgres")`, comments stripped). That SQL is what executes.
- **Refusals** are plain English and name the offending thing: "Only one statement is allowed (found 2).", "Function pg_sleep is not allowed.", "Table raw.transaction_events is outside the analytics schema.", "Column foo does not exist or is not visible."
- **Tests** — an attack corpus of at least 25 cases, each asserting the stage and a reason substring. Include:
  - multi-statement and stacked queries, plus a comment-hidden second statement
  - `set_config`, `pg_sleep`, `SET ROLE`, `RESET ROLE`
  - data-modifying CTEs and `SELECT INTO`
  - `FOR UPDATE`
  - `COPY ... TO PROGRAM`, `DO $$...$$`, `CALL`, `EXPLAIN ANALYZE DELETE`
  - quoted identifiers like `"raw"."transaction_events"`
  - a subquery, union or join reaching `raw`
  - `information_schema` and `pg_catalog`
  - `lo_import`, `dblink`, `TABLE raw.x`, `VALUES ((SELECT pg_sleep(1)))`
  - `PREPARE`, `LISTEN/NOTIFY`, `VACUUM`
  - an unknown column
  - an allowed complex query (CTE + join + window function) that must pass

**Q2: `compiler`.** Build SQL with **sqlglot builders** (`exp.select(...)`, `exp.column`, `exp.Literal.string/number`, `exp.condition` for the trusted catalog filter strings). Never use f-string SQL with plan values.
- Implement `resolve_window` with every preset in `contracts.WindowPreset`, `default_baseline`, `compile_metric`, `metric_value`, `compile_dq_queries` and `compile_recon_queries`, all exactly per CONTRACTS.md.
- **Ratio metrics:** `SUM(CASE WHEN <num filter> THEN <num expr or 1> ELSE 0 END) AS num`, and the same for `den`. Both periods go in one scan: `CASE WHEN date BETWEEN cur THEN 'current' WHEN ... THEN 'baseline' END AS period`, with WHERE covering the union.
- **Columns and filters:** the dimension column comes from the catalog, and filter values are cast per `DimensionDef.dtype`. Values outside a closed vocabulary raise `ValueError` (triage normally catches this first).
- **Time column:** use the metric's `time_column`, falling back to the table's.
- **Tests:**
  - every catalog verified query compiles **and passes `check_sql`**
  - window presets around month and week boundaries (as_of = 2026-11-19, a Thursday)
  - an injection attempt in a filter value (`"UPI' OR 1=1 --"`) is rejected or safely quoted, never executed as SQL

**Q3: `db.run_query` + `db.data_version`** (CONTRACTS.md §2).
- Use psycopg 3 with one connection per query as `persona.db_role` (`# ponytail: per-query connect, pool if latency matters`).
- Run inside a read-only transaction with `SET LOCAL statement_timeout`. Before executing, run `EXPLAIN (FORMAT JSON)` and reject when `Total Cost > max_cost`.
- **Calibrate `max_cost`** on the seeded DB: measure the EXPLAIN cost of the heaviest legit catalog query (14-day two-period breakdown by issuer_bank) and of a self-join of transactions. Pick a default that passes the first with ≥3× headroom and rejects the second. Record both numbers in a comment and your report.
- **Errors** map to `QueryRejected` stages: QueryCanceled → timeout, InsufficientPrivilege → access, other psycopg errors → db (message cleaned of connection details).
- **Cache:** an in-process LRU keyed by `(guarded_sql, persona, data_version)`, returning copies (`# ponytail:` comment). Return `QueryResult` with `sql_hash = sha256(sql)[:12]`.

**Q4: `runs.py`.** `save_run` inserts an AnswerBundle into `app.runs` as `sherpa_app` and swallows/logs its own errors. Also implement `recent_runs` and `run_stats` (p50/p95 from `timings_ms.total`, cost from `llm_usage.cost_usd`, rates by status).

**Q5: DB tests** (`@pytest.mark.db`):
- The same query as `rm_south` vs `head` returns only South vs 4 regions.
- Guard-bypass test: call the low-level execution path with `SELECT * FROM raw.transaction_events` as a persona and expect `access`. This proves the DB backstop even if the guard had a bug.
- A heavy query is rejected at `cost`.
- `pg_sleep`-free timeout: a legit but slow query under a tiny `timeout_ms` gives `timeout`.
- Truncation flag; a cache hit on the second call.
- Every verified query executes as `head` and returns rows.

## Acceptance
- `uv run pytest tests/test_guard.py tests/test_compiler.py` pass with no DB; `-m db` pass on the seeded DB.
- The report lists the attack corpus results table and the calibrated cost numbers.
