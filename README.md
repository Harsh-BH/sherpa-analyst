# Sherpa: a governed AI business analyst for payments data

**Pine Labs "First Prompt", case study 02: Enterprise AI Business Analyst.**

Ask *"Why did success rate drop last week?"* and Sherpa gives you an answer that holds up under questioning:

> **Success rate fell from 92.5% to 91.7%, driven by a shift in payment mix rather than worse segment performance.**
> *Fact:* mix −0.92 pp, rate +0.08 pp. UPI's share rose 45.0% → 58.1% while UPI's own success rate stayed flat (88.5% → 88.7%) · *Hypothesis:* a UPI-heavy grocery merchant onboarded · *Caveat:* PG_C has no data on 16 Nov 02:00–08:00 IST

Every number on that card comes from an executed SQL query you can open. Every sentence is tagged **fact / hypothesis /
recommendation / caveat**, and a checker rejects any number the model typed instead of citing.

**The LLM translates and narrates; deterministic code computes.** The model never invents a number and never sees row-level data.

---

## Why this design

Text-to-SQL alone is not trustworthy enough for a business head:

- **Benchmarks:** frontier models solve about 21% of [Spider 2.0](https://arxiv.org/abs/2411.07763) enterprise tasks.
- **Semantic layers:** dbt's [2026 rerun](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026) measured 100% accuracy inside the layer's scope, against 51–63% for raw text-to-SQL.
- **The brief's own trap:** it lists "a decline explained by mix shift", which is Simpson's paradox. A generic "LLM writes SQL, LLM summarises" system reports it wrongly: it sees UPI dominating and blames UPI.

So Sherpa is a **hybrid**:

1. **Governed metrics.** A YAML catalog shaped like MetricFlow's ratio metrics, with Cortex-style verified queries, is compiled to SQL by code. The LLM only picks names from the catalog.
2. **Off-catalog questions.** These go through a model-written SELECT that is labelled *unverified*, has its confidence capped, and passes through the same safety gate.
3. **"Why" questions.** These get an exact **rate/mix decomposition** (Kitagawa 1955 / Das Gupta 1993). It splits a change in a ratio metric into "the mix moved" and "segments got better or worse", and the two parts add up to the total with no leftover term.

## Quickstart

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 26 with pnpm, and either an `ANTHROPIC_API_KEY` or a logged-in `claude` CLI. With neither, Explore mode still works and needs no LLM.

```bash
cp .env.example .env                 # set POSTGRES_PASSWORD and SHERPA_ROLE_PASSWORD; optionally ANTHROPIC_API_KEY
uv sync
pnpm -C web install                  # Next.js UI dependencies
make up                              # Postgres 17 on localhost:5433
make seed                            # 60 days, ~1.56M payments, planted causes, roles + RLS (~30 s)
make seed-eval                       # second seed (7) in database sherpa_s7, for the eval
make app                             # API on 127.0.0.1:8000 + UI on http://localhost:3000
make test                            # unit, DB and API tests
make e2e                             # browser tests in fixture mode (system Chrome)
pnpm -C web check                    # SSE stream parser self-check, no server needed
make eval                            # Sherpa vs a naive text-to-SQL baseline on both seeds
```

`make app` runs both servers and stops the API when the UI exits; `make api` and `make web` run them in two terminals
instead. The UI proxies `/api/*` to `SHERPA_API_URL` (default `http://127.0.0.1:8000`). `SHERPA_UI_FIXTURES=1 make api`
serves canned answers with no DB or LLM.

Everything in Docker (needs `ANTHROPIC_API_KEY` in `.env` for Ask mode), UI on http://localhost:3000:

```bash
docker compose up -d db && docker compose run --rm seed && docker compose up api web
```

The `api` and `web` images were not built on the build machine because the disk was nearly full. Both Dockerfiles are
written and the compose file passes `docker compose config`, but this path is untested; the local `make app` path is the tested one.

## What to try (the 3-minute demo)

| Persona | Question | What you should see |
|---|---|---|
| Business head | *Why did success rate drop last week?* | A **Simpson's paradox** callout. A waterfall shows −0.92 pp mix vs +0.08 pp rate, so no method got worse. A DQ banner shows PG_C's 6-hour ingestion gap. |
| Business head | *Why did success rate fall on 22 Oct compared with the day before?* | EGRET bank's own rate collapsed, with technical declines 0.6% → 9.9%. The hourly profile shows the outage window. Labelled a hypothesis, with a recommendation. |
| Business head | *Why did card success rate drop on 4 Oct?* | The depth-2 drill-down finds the OSPREY × MASTERCARD cell (96% → 82%). Neither dimension shows it alone. |
| Business head | *Why doesn't the settled amount match GMV on 20 Oct?* | A bridge splits the gap: cutoff timing (23:00 IST cycles) + refunds + MDR fees + missing transactions, summing exactly to the gap. |
| Business head | *What was our success rate last week?* | **A question back:** "excluding drop-offs (91.7%) or including them (85.4%)?" The two readings differ, so Sherpa asks instead of guessing. |
| Regional manager, South | *Compare North vs South success rate* | An explained refusal ("North is outside your access") plus a one-click South-only answer. The database enforces the same rule. |
| Regional manager, South | *Which merchants in the South had the highest GMV in the last 7 days?* | The answer is clean, although one merchant's name contains a prompt-injection payload. The model never sees display names. |

**Explore** mode builds the same plan with pickers and no LLM. **Eval** shows the scorecard. **Runs** shows latency, cost and the cache-hit rate from the run log.

## How it works

```
 persona ─▶ Next.js UI ─▶ FastAPI (stages over SSE): Ask | Explore | Eval | Runs
                │ question                                        ▲ AnswerBundle (claims, evidence, charts, DQ, confidence)
        ┌───────▼────────┐  AnalysisPlan (typed JSON,   ┌───────────────────┐
        │ planner (LLM)  ├──── catalog names only) ───▶ │ triage             ├─ clarify / explained refusal
        └────────────────┘                              │ names·scope·windows│
   Explore pickers (no LLM) ── same AnalysisPlan ───────┴─────────┬─────────┘
                    ┌─────────────────────────────────────────────▼───────────────┐
                    │ compiler: catalog → SQL (sqlglot builders)  │ LLM SQL (unverified) │
                    └─────────────────────────────────────────────┬───────────────┘
      guard  : 1 statement · SELECT only · function/cast allowlists · tables+columns ⊆ access.yaml · LIMIT
      db     : persona's own DB role · READ ONLY · statement_timeout · EXPLAIN cost gate · result-size cap
                    ┌─────────────────────────────────────────────▼───────────────┐
                    │ drivers (rate/mix, z-test + BH, Adtributor, drill) · DQ · reconcile │
                    └─────────────────────────────────────────────┬───────────────┘
                             Evidence[] (SQL + hash, window, filters, values, chart)
                    narrator (LLM sees sanitised aggregates; numbers only as {E3.key} placeholders)
                    claim checker + rule-based confidence → app.runs → UI
```

Each module, and how it maps to the brief:

| Brief asks for | Where |
|---|---|
| ≥ 2 related datasets | `analytics.transactions`, `merchants`, `banks`, `settlements`, `dq_daily` (db/schema.sql) |
| NL questions → SQL, executed | `sherpa/planner.py` → `triage.py` → `compiler.py` / guarded LLM SQL → `db.py` |
| Show the steps | the plan, every SQL with its hash, timings, and stage-by-stage progress in the UI |
| Charts and tables | `sherpa/charts.py` (Vega-Lite) with chart choice by code; segment and evidence tables |
| Cite dataset, filters, window | every `Evidence` carries tables, filters, window/baseline and SQL; each claim links to its evidence |
| Facts vs hypotheses vs recommendations | `narrate.check_claims` enforces the kinds and rejects uncited facts and typed numerals (digits *and* number words) |
| Stretch: role-based access | `db/access.yaml` → Postgres login role per persona, column GRANTs, `FORCE ROW LEVEL SECURITY`, plus app-side explained refusals |
| Stretch: data-quality checks | `sherpa/dq.py`: duplicates, ingestion gaps vs a same-hour baseline, nulls, freshness, all shown with the answer |
| Stretch: cohort comparison and drill-down | `compare_periods`, depth-2 drill-down in `drivers.explain_change` |
| Stretch: cost/timeout controls and caching | EXPLAIN max-node-cost gate, `statement_timeout`, row cap (refused, never silently cut) and 50 MB byte cap, LRU cache keyed by (SQL, persona, data version, max rows) |
| Stretch: known-answer evaluation | `eval/`: gold SQL, planted causes, refusals and clarifications, on two seeds vs a naive baseline |
| Stretch: confidence and uncertainty | `narrate.confidence`: rule-based with stated reasons; two-proportion z-tests with Benjamini–Hochberg q-values |

### The brief's failure scenarios

| Scenario | Mechanism |
|---|---|
| Missing or duplicate records | `raw.transaction_events` keeps duplicate webhooks, and `analytics.transactions` dedups. `dq_daily` counts both. Ingestion gaps are found per gateway against the same hour's 7-day median, and the warning is shown with the answer and cited verbatim by the narrator. |
| Out-of-scope access | Triage refuses *before* any SQL, with the reason and an in-scope offer. If the app had a bug, Postgres RLS on `region` (FORCE, per-persona login role) still returns only allowed rows. A test bypasses the guard on purpose to prove it. |
| Two sources disagree | `reconcile.py` splits transactions-vs-settlements into cutoff timing, missing transactions, refunds and fees. The identity is asserted, and `source_of_truth` is declared per metric. |
| Mix shift explains a decline | The symmetric rate/mix decomposition with a Simpson flag (below). |
| Ambiguous period or denominator | Vague periods are resolved to explicit dates and stated as assumptions. For "success rate" Sherpa **computes both definitions and asks only if they tell different stories** (opposite direction, or material vs not). |
| Expensive or unsafe query | The sqlglot guard (63-case attack corpus, plus the review's regression cases), Postgres grants, a read-only transaction, `statement_timeout`, an EXPLAIN max-node-cost gate, and row and byte caps. |

### Driver engine

For a ratio metric R = S/N with segment shares c = n/N and rates r = s/n, between baseline (0) and current (1):

```
ΔR = Σ (c1 − c0)·((r0 + r1)/2 − R̄)      mix  (R̄ = (R0 + R1)/2)
   + Σ (r1 − r0)·(c0 + c1)/2            rate
```

The two sums equal ΔR exactly, and a unit test asserts it to 1e-12 on random frames. Worked example from the tests:
cards 60% → 40% of volume at 96.0% → 96.5%, UPI 40% → 60% at 88.0% → 88.5%. Overall 92.8% → 91.7% = **mix −1.60 pp + rate +0.50 pp**.
Both methods improved, yet the total fell.

On top of that:
- **Significance:** a two-proportion z-test per segment, with Benjamini–Hochberg across the whole report.
- **Gates:** support (n ≥ 1,000, ≥ 1% share) and materiality (≥ 0.3 pp and ≥ 5% of the change).
- **Mix test:** a chi-square test of the share shift.
- **Ranking:** dimensions are ranked by how much of the change they explain, so a single broken bank outranks the payment method it runs on.
- **Cross-check:** an Adtributor (NSDI'14) explanatory-power check.
- **Drill-down:** a depth-2 drill-down over the top dimension pairs.

## Evaluation

<!-- EVAL:START -->
`make eval` runs **28 cases per seed on two seeds** (42 in `sherpa`, 7 in `sherpa_s7`). Planted-cause parameters differ per
seed: a different bank, day and card network. Sherpa runs against a **naive baseline**: one LLM call writes SQL from the schema
DDL, and a second summarises the rows. Both use the same models. Results from a fresh run on commit `2f13f1c`
(`eval/results/latest.json`, also on the Eval page):

| Metric (both seeds) | Sherpa | Naive baseline |
|---|---|---|
| Known answers: result equals hand-written gold SQL (Genie's 4-significant-digit rule) | **100%** (20/20) | 10% |
| Planted causes found (S1 mix + Simpson, S2 issuer, S3 issuer×network cell) | **100%** | 75%* |
| Correct refusals (out-of-scope region, forecast, delete, PII) | **100%** | 33% |
| Correct clarifications (ambiguous denominator) | **100%** | 0% |
| Prompt-injection text kept out of the answer (S6) | **100%** | 0% |
| Unsafe-SQL plans stopped (multi-statement, `set_config`, raw schema, `pg_sleep`, cross join) | **100%** | n/a |
| Numbers in the answer that no executed result supports | **0** | **72** |
| Median latency | 12.1 s | 16.3 s |
| LLM cost for the run | $1.49 | $3.71 |
| **Cases passed** | **56 / 56** | **17 / 56** |

\* The baseline is graded leniently on purpose. It gets keyword rules ("mentions UPI and mix/share"), its SQL is told the guard's
limits and gets one repair round, and it runs **through Sherpa's guard and DB roles**. That makes it safer than a real naive
system, which would execute whatever the model wrote. Grading rules and known limits are in `eval/README.md`.

What this does **not** prove: the planted causes come from our own generator, so this is a regression and contrast harness, not an
external benchmark. Two seeds with randomised parameters and gold SQL written independently of the compiler limit the circularity;
they do not remove it. For the plain level question "What was our success rate in the last 7 days?", Sherpa asks which
denominator is meant (the readings differ by about 6 pp), and the eval answers with the governed default. That is recorded in the case detail.
<!-- EVAL:END -->

## Synthetic data, honestly

No public dataset has bank, method and decline-type fields; PaySim has none of them. `gen/generate.py` produces 60 days
(21 Sep – 19 Nov 2026 IST), about 25k attempts/day. Levels are calibrated to published NPCI-style figures: UPI ≈ 88.5% and cards ≈ 96%
success excluding drop-offs, and drop-offs ≈ 7%.

It plants six causes, with parameters drawn from the seed:

| | Planted cause |
|---|---|
| S1 | A UPI-heavy merchant onboards (mix shift) |
| S2 | An issuer's technical declines spike for six hours |
| S3 | One issuer × card-network 3DS failure |
| S4 | Settlement cutoff, refunds and fees |
| S5 | Duplicate webhooks and a 6-hour ingestion gap |
| S6 | A merchant name carrying a prompt injection |

`data/ground_truth_<seed>.json` records the expected answers. They are computed from the generated arrays **and** re-derived in SQL
from the loaded tables, and the load rolls back if the two disagree. All bank and merchant names are fictional.

## Security model

1. **Two layers.** The app explains refusals; Postgres enforces them. Both are generated from `db/access.yaml`, and tests assert the column grants equal that file.
2. **Per-persona database roles.** Each persona has a login role with read-only sessions, column-level `SELECT` on `analytics.*` only, and `FORCE ROW LEVEL SECURITY`. Dangerous built-ins (`ts_stat`, `pg_cancel_backend`, large-object writers…) are revoked, and there is no CONNECT or TEMP on other databases.
3. **The guard parses with sqlglot and regenerates the SQL.**
   - Exactly one statement, SELECT or set operation only, no data-modifying CTEs, `INTO`, locks or session commands.
   - Function and cast allowlists, with no field-selection calls (`(x).fn`).
   - Tables and columns are validated with `qualify()` against the allowlist.
   - The LIMIT is enforced, including `FETCH … WITH TIES`.
4. **Execution limits.** Queries run in a read-only transaction with `SET LOCAL statement_timeout`. An EXPLAIN gate checks the **maximum node cost** in the plan, and rows are streamed one at a time under a 50 MB result budget.
5. **What the LLM sees.** Only sanitised aggregates: closed-vocabulary values, ids, numbers, and code-generated DQ messages. No display names, no free text, and no rate cells under the support threshold.
6. **Adversarial review.** An independent multi-agent review tried to break each layer and reproduced 24 issues. All are fixed with regression tests (see `docs/TASKS.md`). The worst was `(expr).fname` field-selection syntax calling arbitrary functions past the allowlist. Row data stayed protected by the DB layer throughout.

## Assumptions, mocks, limitations

- **The data is synthetic.** The planted causes make evaluation possible but partly circular: we detect what we planted. Mitigations: parameters are randomised per seed, two seeds are used, and a naive baseline runs on the same data.
- **Decomposition is association, not causation.** Mechanisms ("issuer outage", "new merchant") are always tagged *hypothesis*.
- **Catalog coverage bounds the trusted route.** Off-catalog questions use labelled, capped, guarded LLM SQL.
- **Persona login is a selector, not authentication** (a demo). Real deployment would map SSO identities to the DB roles.
- **LLM backends.** The Anthropic API (`ANTHROPIC_API_KEY`) or the local `claude` CLI. The CLI path was used for development and evaluation; the API path is unit-tested but was not run live here (no key on the build machine).
- **Volume leak through planner statistics.** These leak per-region volume to anyone with a direct DB login; personas never get one.
- **The API is one process.** The query cache is per process.
- **Docker coverage.** The Python image was built and verified with the earlier Streamlit UI (health endpoint, plus a full pipeline answer from inside the container against the compose DB). The `api` service (same image, uvicorn instead of Streamlit) and the Next.js `web` image have not been built, and the one-shot `seed` service was not run on the build machine (disk space). The local `make seed` and `make app` paths are the tested ones.

## Repository layout

```
sherpa/           contracts.py (shared types) · config.py · catalog.yaml (governed metrics)
                  planner.py · triage.py · compiler.py · guard.py · db.py · runs.py
                  drivers.py · dq.py · reconcile.py · narrate.py · charts.py · pipeline.py · llm.py
app/              FastAPI for the UI: api.py (ask over SSE, meta, explore, eval, runs) · view.py (every number as a string)
web/              Next.js UI (Ask, Explore, Eval, Runs) · e2e/ (Playwright, fixture mode)
db/               schema.sql · access.yaml · roles.py (grants + RLS from access.yaml) · build_analytics.sql
gen/              seeded generator + planted scenarios + ground truth
eval/             gold SQL, cases, naive baseline, runner
tests/            unit, DB, end-to-end pipeline and API tests
docs/             ARCHITECTURE.md · CONTRACTS.md · TASKS.md · agents/ (how it was built)
```

## How it was built

A master agent wrote the contracts (`sherpa/contracts.py`, `docs/CONTRACTS.md`), the schema and the catalog. It then ran five Claude Code
agents in parallel tmux sessions, one git worktree and branch each: data, sql, analytics, ai and ui. Agents coordinated through
contract files and question/answer files, not chat. The master reviewed and merged each branch, wrote the integration
(`sherpa/pipeline.py`), and ran an adversarial multi-agent review whose findings were fixed with regression tests. See `docs/TASKS.md`.

## Credits and licences

**Dependencies:** sqlglot (MIT), psycopg (LGPL), pandas, numpy, scipy, statsmodels (BSD), pydantic (MIT), FastAPI (MIT),
uvicorn (BSD), anthropic SDK (MIT), Altair (BSD, tests only). UI: Next.js, React, Tailwind CSS, Radix UI, shadcn/ui,
react-resizable-panels (MIT), lucide-react (ISC), Vega, Vega-Lite and vega-embed (BSD).

**Adapted code (with attribution in the files):**
- Result-set comparison from [defog-ai/sql-eval](https://github.com/defog-ai/sql-eval) (Apache-2.0).
- Adtributor explanatory-power and surprise formulas following [shaido987/riskloc](https://github.com/shaido987/riskloc) (MIT).

**Ideas, not code:**
- Systems: [WrenAI](https://github.com/Canner/WrenAI) (re-validating expanded SQL), Snowflake Cortex Analyst (verified queries, suggestions on ambiguity), dbt MetricFlow (ratio metric shape), Databricks Genie (benchmark rule: same result set at 4 significant digits).
- Write-ups: Swiggy Hermes V3 (clarify step, stated assumptions, confidence), LinkedIn SQL Bot (multiple acceptable answers), InsightBench (planted insights), Zhong et al. 2020 (test suites on perturbed databases).
- Methods: Bhagwan et al. NSDI 2014 (Adtributor), Kitagawa 1955 and Das Gupta 1993 (decomposition).
