# Brief: data agent (infrastructure + synthetic data)

You own the **critical path**: every DB-backed test and the whole demo wait on your seeded database.
Land D4 (roles) and a first seeded DB (D1+D3) as early as you can, then refine.

**You own:** `gen/` (generator package), `db/build_analytics.sql`, `db/roles.py`, `docker-compose.yml`,
`Dockerfile`, `.dockerignore`, `Makefile`, `tests/test_data_*.py`, and the outputs under `data/` (gitignored).
**Read but don't edit:** `db/schema.sql`, `db/access.yaml`, `sherpa/catalog.yaml` (the dimension
vocabularies there are the exact values you must generate), and `sherpa/config.py`.

The DB is already running (`docker compose up -d db`, schema applied, empty). Connect as admin via
`sherpa.config.settings().admin_dsn()`.

## Tasks

**D4: roles, grants and RLS from access.yaml** (start here; ~1h).
`uv run python -m db.roles [--dry-run] [--db NAME]` generates and applies idempotent SQL:
- Login roles for each persona `db_role` and for `app_role`, with password `$SHERPA_ROLE_PASSWORD`.
- `REVOKE ALL` on schemas `raw` and `app` (and their tables) from PUBLIC and the personas.
- `GRANT USAGE ON SCHEMA analytics` to personas.
- **Column-level** `GRANT SELECT (cols...)` on each `exposed_tables` table, and nothing else.
- On every exposed table that has a `region` column: `ENABLE` + `FORCE ROW LEVEL SECURITY` and one policy per persona, `FOR SELECT TO <role> USING (region = ANY (ARRAY[...]))`.
- `ALTER ROLE <persona> SET default_transaction_read_only = on`, `SET statement_timeout = '5s'`, `SET search_path = analytics`.
- `sherpa_app` gets `USAGE` on schema app plus `INSERT, SELECT` on `app.runs` only, and no analytics access.
- `--dry-run` prints the SQL.

**D1: generator core.** `uv run python -m gen.generate --seed 42 [--db NAME] [--days 60]`, numpy-vectorised, loading with COPY (psycopg `cursor.copy`). It must run in under 3 minutes for 60 days.
- Range is 2026-09-21..2026-11-19 IST (as_of = 2026-11-19; `--days` shortens from the end for fast tests). About 25k attempts per day, with weekday seasonality ±10% and an hour-of-day curve peaking 11–14h and 19–22h.
- 10 fictional banks, using the ids in catalog `issuer_bank.values` (`KESTREL` → "Kestrel Bank"), with mixed `bank_type`.
- ~2,000 merchants: regions North 30 / South 30 / West 25 / East 15, the 8 catalog categories, plausible Indian cities per tier, an MCC per category, and `onboarded_on` dates.
- Method mix: UPI 45 / CARD 35 / NETBANKING 10 / WALLET 10, skewed by category (fuel and grocery lean UPI; travel and electronics lean card).
  - `card_network` for CARD only: VISA 45 / MASTERCARD 30 / RUPAY 25.
  - `issuer_bank_id` is NULL only for WALLET.
  - Gateways PG_A 50 / PG_B 30 / PG_C 20.
  - Devices android 55 / ios 15 / web 20 / pos 10.
- Outcomes:
  - DROPPED ≈ 7% of attempts.
  - Among SUCCESS+FAILED: UPI ≈ 88.5% success (BD ≈ 11%, TD ≈ 0.5%), CARD ≈ 96%, NETBANKING ≈ 93%, WALLET ≈ 97.5%.
  - Fixed per-bank offsets of ±1.5 pp, plus small daily noise.
  - `decline_code` comes from the catalog `decline_code.values`. BUSINESS codes: INSUFFICIENT_FUNDS, INCORRECT_PIN, LIMIT_EXCEEDED, RISK_DECLINED. TECHNICAL codes: ISSUER_TIMEOUT, ISSUER_SWITCH_DOWN, ACS_3DS_FAILURE (cards only), GATEWAY_ERROR.
- Amounts are lognormal by category, with medians: grocery ₹450, electronics ₹6,000, travel ₹4,500, fuel ₹1,200, restaurants ₹700, pharmacy ₹400, apparel ₹1,800, utilities ₹1,500.
- `ingested_at = created_at + Exp(mean 20 s)`. `attempt_no` is mostly 1.
- Settlements per merchant per cycle follow the semantics in docs/CONTRACTS.md §1: refunds are ~0.2% of gross (random per row) and fee = 1.8% of gross.
  - They are computed from the **true** sales, before S5 ingestion loss.
  - The UTR is a random 12-char string.
- Determinism: the same seed gives a byte-identical dataset. Write `data_version.version = f"seed{seed}-{sha256(params+row counts)[:8]}"`.

**D2: planted scenarios S1–S6** (docs/ARCHITECTURE.md table). Draw parameters from the seed (which bank, which day, which network), and write `data/ground_truth_<seed>.json`:
```json
{"seed": 42, "data_version": "...", "data_start": "2026-09-21", "as_of": "2026-11-19",
 "scenarios": [
  {"id": "S1", "kind": "mix_shift", "metric": "success_rate",
   "window": {"start": "2026-11-13", "end": "2026-11-19"}, "baseline": {"start": "2026-11-06", "end": "2026-11-12"},
   "filters": [], "expected": {"effect": "mix", "direction": "down", "simpson": true,
     "dimension_any_of": ["payment_method", "merchant_category"], "segment_any_of": ["UPI", "grocery"]},
   "facts": {"upi_share_baseline": 0.45, "upi_share_current": 0.58},
   "question": "Why did success rate drop last week?"},
  {"id": "S2", "kind": "issuer_outage", "metric": "success_rate", "window": {...day D...}, "baseline": {...D-1...},
   "expected": {"effect": "rate", "direction": "down", "dimension": "issuer_bank", "segment": "<BANK>",
                "decline_type": "TECHNICAL", "hours": [10, 15]},
   "question": "Why did success rate fall on <D, e.g. 28 Oct> compared with the day before?"},
  {"id": "S3", "kind": "issuer_network_3ds", "filters": [{"dimension": "payment_method", "op": "in", "values": ["CARD"]}],
   "expected": {"effect": "rate", "cell": {"issuer_bank": "<BANK2>", "card_network": "<NET>"}}, ...},
  {"id": "S4", "kind": "reconciliation", "window": {...one date...},
   "expected": {"txn_gmv_inr": 0, "settled_net_inr": 0, "cutoff_timing": 0, "missing_transactions": 0, "refunds": 0, "fees": 0}, ...},
  {"id": "S5a", "kind": "duplicates", "expected": {"date": "...", "gateway": "PG_B", "duplicate_events": 1200}},
  {"id": "S5b", "kind": "missing_data", "expected": {"date": "2026-11-16", "gateway": "PG_C", "hours": [2, 7]}},
  {"id": "S6", "kind": "prompt_injection", "expected": {"merchant_id": "...", "display_name": "..."}}]}
```
Everything in `expected` must be **computed from the generated data**, not hard-coded. S1 must keep each method's rates flat: the new merchant uses the same per-method and per-bank outcome model. Pick the S1 merchant's region as South, so `rm_south` sees it. Make S2, S3 and S4 dates distinct from each other and from the S1 and S5 windows. Use fictional names everywhere: never a real bank, merchant or brand.

**D3: `db/build_analytics.sql`** fills `analytics.*` from `raw.*`:
- Deduplicate to the latest `ingested_at` per `txn_id`.
- Denormalise merchant `region`, `category` → `merchant_category`, and `city_tier`.
- Add `txn_date`, `txn_hour` and `cycle_date` in Asia/Kolkata.
- Copy settlements with region.
- Fill `dq_daily` from raw.
- Write the single `data_version` row, then `ANALYZE`.

`make seed` (D5) runs generate → build_analytics → roles, so re-seeding is one command and idempotent (truncate and reload).

**D5: Makefile + compose + Dockerfile.**
- Makefile targets: `up` (db), `seed` (SEED ?= 42, DB ?= sherpa), `seed-eval` (seed 7 into database `sherpa_s7`, created if missing, with schema + build + roles), `test`, `app`, `eval` (runs `uv run python -m eval.run` if present), `down` (never `-v`).
- Add an `app` service to docker-compose.yml (built from `Dockerfile`, python:3.12-slim + uv, runs streamlit on 8501, depends on db healthy, env from .env, `SHERPA_DB_HOST=db`), plus a one-shot `seed` service or a documented `docker compose run` command.
- **Do not build the image**: the disk is full. The master verifies it at the end. Keep `.dockerignore` tight (.venv, data, .git).

**D6: tests** (`tests/test_data_*.py`, marked `db` where needed):
- Determinism: two `--days 3` runs into a scratch database give identical row hashes. Use a scratch DB `sherpa_test`, created and dropped by the test; never touch `sherpa` from tests.
- RLS: `sherpa_rm_south` sees only South on every RLS table, cannot read `raw.*` or `app.runs`, and cannot INSERT. `sherpa_head` sees all 4 regions.
- Column grants equal access.yaml: compare against `information_schema.column_privileges`.
- Ground truth reproduces against the DB: S1 shares, S5a duplicates, S5b zero rows in the hours, and the S4 identity.
- Calibration: overall UPI and CARD success rates are within ±1.5 pp of target in a non-scenario week.

## Acceptance
- `make seed` from an empty DB finishes in under 5 min, and `analytics.data_version` has one row.
- All D6 tests pass, and the ground truth file exists for seeds 42 and 7.
- Report the actual volumes, rates, duplicate counts, the DB size (`pg_database_size`) and seed runtime in your report.
- **Post an early status line as soon as `sherpa` is seeded once**, even before D2 is perfect: other agents are waiting.
