# Sherpa: governed AI business analyst (Pine Labs First Prompt, case 02)

Answers "why did success rate change?" over payments data. The LLM plans and narrates; deterministic code computes; every number traces to an executed, stored query.

## Stack

Python 3.12 (uv) · Postgres 17 in docker (host port 5433) · sqlglot · pandas/statsmodels · FastAPI (`app/`) + Next.js in `web/` (pnpm, Node 26) · Claude via the anthropic SDK or `claude -p`.

## Commands

| | |
|---|---|
| install | `uv sync` · `pnpm -C web install` |
| db up | `docker compose up -d db` |
| seed | `make seed` (SEED=42) |
| test | `uv run pytest` (`-m db` needs a seeded DB, `-m live` makes LLM calls); `make e2e` (browser, fixture mode) |
| app | `make app` (API 127.0.0.1:8000 + UI http://localhost:3000; `SHERPA_UI_FIXTURES=1` = no DB/LLM) |

## Layout

```
sherpa/contracts.py  shared types: the contract between modules (signatures: docs/CONTRACTS.md)
sherpa/catalog.yaml  governed metrics, dimensions, verified queries
db/access.yaml       personas -> DB roles, regions, column allowlist (guard + DB grants both read it)
db/schema.sql        raw.* (as ingested) / analytics.* (what personas query) / app.runs
docs/TASKS.md        task DAG + status (master owns); docs/agents/ = per-agent briefs
```

## Conventions

- The LLM never computes or types numbers: narrator text uses `{E<n>.<key>}` placeholders filled from Evidence.
- The LLM sees aggregates only, never row-level data or merchant display names.
- Every SQL statement (compiled or LLM-written) goes through `guard.check_sql`, then `db.run_query` as the persona's DB role.
- Rates are fractions (0.917); rate deltas are fractions rendered as pp; money is INR.

## Gotchas

- Port 5432 is another project's Postgres; ours is 5433 (container `sherpa-db`).
- Disk is ~97% full: no new docker images; never `docker compose down -v`, never prune volumes.
- "Today" is `analytics.data_version.as_of`, not the wall clock.

## Don't

- Edit contracts.py, schema.sql, catalog.yaml, access.yaml, config.py outside the master branch.
- Commit `.env` or anything under `data/`.
