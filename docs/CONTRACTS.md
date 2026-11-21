# Engineering contracts

Types live in `sherpa/contracts.py`. This file fixes the **function signatures, data shapes and
semantics** each module promises. Code against these; if one is wrong or missing, raise it through
the protocol (docs/agents/PROTOCOL.md). Do not work around it silently.

## 0. Ownership

| Path | Owner |
|---|---|
| `sherpa/contracts.py`, `sherpa/config.py`, `sherpa/catalog.yaml`, `db/schema.sql`, `db/access.yaml`, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `docs/*`, `tests/conftest.py` | master |
| `sherpa/pipeline.py`, `tests/test_pipeline*.py` | master (integration) |
| `gen/`, `db/build_analytics.sql`, `db/roles.py`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`, `Makefile`, `tests/test_data_*.py` | **data** |
| `sherpa/guard.py`, `sherpa/compiler.py`, `sherpa/db.py`, `sherpa/runs.py`, `tests/test_guard.py`, `tests/test_compiler.py`, `tests/test_db.py`, `tests/test_runs.py` | **sql** |
| `sherpa/drivers.py`, `sherpa/dq.py`, `sherpa/reconcile.py`, `tests/test_drivers.py`, `tests/test_dq.py`, `tests/test_reconcile.py`, `eval/` (wave 2) | **analytics** |
| `sherpa/llm.py`, `sherpa/planner.py`, `sherpa/triage.py`, `sherpa/narrate.py`, `sherpa/prompts/`, `tests/test_llm.py`, `tests/test_planner.py`, `tests/test_triage.py`, `tests/test_narrate.py` | **ai** |
| `app/`, `web/`, `sherpa/charts.py`, `tests/fixtures/`, `tests/test_charts.py`, `tests/test_api.py`, `tests/test_view.py`, `tests/test_backend.py`, `tests/test_chart_colors.py` | **ui** |

## 1. Database (db/schema.sql, db/access.yaml)

* Postgres 17, database `sherpa`, `localhost:5433`, superuser `postgres` / `$POSTGRES_PASSWORD`.
* Persona login roles: `access.yaml` `personas.*.db_role` (`sherpa_head`, `sherpa_rm_south`), password `$SHERPA_ROLE_PASSWORD`.
  They can only `SELECT` the `exposed_tables` columns in schema `analytics`, as row-level security on `region` allows. Their sessions default to `default_transaction_read_only=on`, `statement_timeout=5s` and `search_path=analytics`.
* App role `sherpa_app` (same password): `INSERT, SELECT` on `app.runs` and `app.run_feedback` only (no UPDATE or DELETE: feedback is insert-only, the latest row per run wins).
* `analytics.data_version` has exactly one row, and its `as_of` is "today" for relative windows. Data range: `data_start = 2026-09-21` through `as_of = 2026-11-19` (60 days) for every seed.
* Settlement semantics: `cycle_date(created_at) = IST date of (created_at + 1 hour)`, i.e. a 23:00 IST cutoff. `settlement_date = cycle_date + 1`, and `net = gross - refund - fee`. Settlements are generated from the *true* sales, before any ingestion loss.

## 2. sql agent

```python
# sherpa/guard.py
@dataclass
class GuardResult:
    sql: str                 # regenerated SQL (comments stripped, LIMIT enforced) — this is what runs
    tables: list[str]        # analytics tables referenced (unqualified names)
def check_sql(sql: str, *, max_rows: int = MAX_ROWS) -> GuardResult      # raises QueryRejected(stage="parse"|"policy")
#   The allowlist is load_access().exposed_tables (schema analytics only). It is identical for every persona: region scope is RLS's job.

# sherpa/compiler.py
def resolve_window(w: TimeWindow, as_of: date, data_start: date) -> TimeWindow     # fills start/end/label; clamps to data range
def default_baseline(w: TimeWindow) -> TimeWindow                                 # equal-length window immediately before w
def compile_metric(metric: str, *, window: TimeWindow, dimensions: list[str] = [], filters: list[Filter] = [],
                   baseline: TimeWindow | None = None, grain: Literal["day","hour"] | None = None) -> str
#   Output columns, in order: *dimensions, ["period"] (only if baseline; values 'baseline'|'current'),
#   ["bucket_date"] (if grain), ["bucket_hour"] (if grain == "hour"), "num", "den".
#   ratio metric: num = numerator measure, den = denominator measure.
#   simple metric: num = measure, den = COUNT(*) of rows passing the measure filter (support).
#   Windows must already be resolved. Filter values are validated against the dimension's vocabulary, emitted as typed literals and never string-interpolated.
def metric_value(metric: str, num: float, den: float) -> float | None             # ratio: num/den (None if den == 0); simple: num
def compile_dq_queries(window: TimeWindow, filters: list[Filter] = []) -> dict[str, str]
#   {"dq_daily": rows of analytics.dq_daily for the window,
#    "hourly":   txn_date, txn_hour, gateway, attempts for [window.start - 7 days, window.end]}
def compile_recon_queries(window: TimeWindow, filters: list[Filter] = []) -> dict[str, str]
#   {"by_txn_date":   txn_date, gmv_inr (successful sales by calendar date, window),
#    "by_cycle_date": cycle_date, gmv_inr (successful sales by settlement cycle, window),
#    "settlements":   cycle_date, gross_inr, refund_inr, fee_inr, net_inr (window)}

# sherpa/db.py
def run_query(sql: str, persona: str, *, max_rows: int = MAX_ROWS, timeout_ms: int = STATEMENT_TIMEOUT_MS,
              max_cost: float | None = None, use_cache: bool = True) -> QueryResult
#   Order: guard -> cache lookup -> connect as the persona's DB role -> BEGIN READ ONLY -> SET LOCAL statement_timeout
#   -> EXPLAIN (FORMAT JSON) cost gate -> execute (fetch max_rows + 1 to detect truncation) -> ROLLBACK.
#   Raises QueryRejected(stage=parse|policy|cost|timeout|access|db).
def data_version(persona: str) -> dict        # {"version", "seed", "data_start", "as_of"} (dates as date)

# sherpa/runs.py — app.runs.source is $SHERPA_RUN_SOURCE at save time (default 'app'; pytest 'test', eval/run.py 'eval').
#   The readers return source = 'app' rows only, so test and eval traffic never reaches the Runs page.
def save_run(bundle: AnswerBundle) -> None    # as sherpa_app; never raises into the caller (logs instead)
def recent_runs(limit: int = 50) -> list[dict]
def run_series(limit: int = 2000) -> list[dict]   # oldest first: run_id, asked_at, status, timings_ms, cost_usd (Runs charts)
def run_stats() -> dict                       # {"runs", "p50_ms", "p95_ms", "refusal_rate", "clarify_rate", "cache_hit_rate", "llm_cost_usd", "helpful_rate"}
#   app.runs.bundle keeps the whole AnswerBundle. These three return a run only to its own persona, and only when it has a bundle:
def history(persona: str, limit: int = 20) -> list[dict]          # app runs, newest first: run_id, question, status, confidence, asked_at
def get_run(run_id: str, persona: str) -> AnswerBundle | None
def save_feedback(run_id: str, persona: str, rating: int) -> bool  # 1 or -1 into app.run_feedback; False = not found
```

## 3. analytics agent

All functions are pure (pandas in, contract models out), with no DB access.

```python
# sherpa/drivers.py
def decompose(df: pd.DataFrame, dimension: str) -> DimensionDecomposition
#   df columns: [<dimension>, "period", "num", "den"]; period in {"baseline","current"}; one row per segment x period.
#   Symmetric (Kitagawa / Das Gupta) split; sum(mix) + sum(rate) == delta to 1e-12. Tests are local, BH is not applied here.
def explain_change(frames: dict[str, pd.DataFrame], *, metric: str, window: str, baseline: str,
                   drill: dict[tuple[str, str], pd.DataFrame] | None = None) -> DriverReport
#   frames: dimension -> frame shaped as for decompose. Applies BH across ALL segment tests in the report,
#   ranks dimensions by .score, sets top_dimension and simpson_flag. drill: (d1, d2) -> frame with
#   columns [d1, d2, "period", "num", "den"] -> report.drilldown (top cells).
def evidence_from_report(report: DriverReport, start_id: int) -> list[Evidence]
#   Numbers the narrator may cite. Keys are stable snake_case (e.g. r0, r1, delta, mix_total, rate_total,
#   <segment>_share0, <segment>_rate_effect ...) with formats set.

# sherpa/dq.py
def run_checks(dq_daily: pd.DataFrame, hourly: pd.DataFrame, *, window: TimeWindow, as_of: date) -> list[DQWarning]
#   dq_daily: analytics.dq_daily rows; hourly: [txn_date, txn_hour, gateway, attempts] covering window.start - 7 days .. window.end

# sherpa/reconcile.py
def reconcile(by_txn_date: pd.DataFrame, by_cycle_date: pd.DataFrame, settlements: pd.DataFrame,
              *, window: TimeWindow) -> ReconResult
#   Identity (asserted): gap = txn_gmv - settled_net
#     = (txn_gmv - cycle_gmv)            -> cutoff_timing
#     + (cycle_gmv - settled_gross)      -> missing_transactions (negative = settlements contain sales we never ingested)
#     + refunds + fees
#   with unexplained = whatever float residue is left (should be ~0).
```

## 4. ai agent

```python
# sherpa/llm.py
class LLMUnavailable(Exception): ...
def backend() -> str                                   # "anthropic" | "claude-cli" | "none" (resolves "auto")
def structured(*, system: str, user: str, schema: dict, model: str, max_tokens: int = 4096) -> tuple[dict, dict]
#   -> (parsed JSON matching schema, usage {"backend","model","input_tokens","output_tokens","cost_usd","latency_ms"})

# sherpa/planner.py
def plan(question: str, persona: str, *, as_of: date, data_start: date) -> tuple[AnalysisPlan, dict]   # (plan, usage)

# sherpa/triage.py
@dataclass
class TriageResult:
    action: Literal["proceed", "clarify", "refuse"]
    plan: AnalysisPlan                     # normalised: canonical names/values, default windows filled (as presets)
    clarification: Clarification | None
    refusal: Refusal | None
    variant_metrics: list[str]             # denominator variants the pipeline must compute before deciding to ask
def triage(plan: AnalysisPlan, persona: str) -> TriageResult

# sherpa/narrate.py
def sanitize(evidence: list[Evidence]) -> list[dict]   # what the LLM may see: aggregates only, small cells suppressed, no free text
def narrate(question: str, plan: AnalysisPlan, evidence: list[Evidence], *, drivers: DriverReport | None = None,
            dq: list[DQWarning] = []) -> tuple[Narrative, dict]          # LLM; one repair round on checker failure
def template_narrative(plan: AnalysisPlan, evidence: list[Evidence], *, drivers: DriverReport | None = None,
                       dq: list[DQWarning] = []) -> Narrative            # no-LLM fallback, same placeholder rules
def check_claims(narrative: Narrative, evidence: list[Evidence]) -> tuple[str, list[CheckedClaim]]   # (rendered headline, claims)
def confidence(plan: AnalysisPlan, route: str, evidence: list[Evidence], claims: list[CheckedClaim],
               dq: list[DQWarning], drivers: DriverReport | None, *, dropped_claims: int = 0) -> tuple[str, list[str]]
#   narrate() reports usage["dropped_claims"]; the pipeline passes it here.
```

### Evidence value keys (what `{E<n>.<key>}` may cite)
`segkey` = segment label sanitised by `drivers` (same function everywhere). Rates use `pct`, rate deltas `pp`, money `inr`, counts `int`.

| kind | keys | table rows |
|---|---|---|
| metric | `value`, `num`, `den` | – |
| breakdown | `value` (overall), `<segkey>_value`, `<segkey>_den`, `<segkey>_share` (additive: value / overall) or `<segkey>_den_share` (ratio: volume share) | `{segment, key, value, den}` |
| trend | `first`, `last`, `change`, `min`, `max`, `min_at`, `max_at` (text) | `{bucket, value, den}` |
| comparison | `r0`, `r1`, `delta`, `<segkey>_r0`, `<segkey>_r1`, `<segkey>_delta` | `{segment, key, r0, r1, delta, n0, n1}` |
| decomposition / drilldown | as produced by `drivers.evidence_from_report` | rows carry `segment` + `key` |
| segment_test (decline split) | `td_r0`, `td_r1`, `td_delta`, `bd_r0`, `bd_r1`, `bd_delta` | – |
| reconciliation | `txn_gmv_inr`, `settled_net_inr`, `gap_inr`, `cutoff_timing`, `missing_transactions`, `refunds`, `fees`, `unexplained` | components |
| dq_check (one per DQWarning) | the warning's `values` + text `check`, `severity` | – |

Reserved keys that `check_claims` resolves on any evidence: `window`, `baseline`, `<segkey>_segment` (the `segment` of the row whose `key` is segkey).

## 5. ui agent

```python
# sherpa/charts.py — Vega-Lite dicts, deterministic chart choice, no LLM
def waterfall(dec: DimensionDecomposition, top_n: int = 6) -> dict      # mix vs rate per segment + total
def bars(rows: list[dict], x: str, y: str, fmt: ValueFormat, color: str | None = None) -> dict
def trend(rows: list[dict], x: str, y: str, fmt: ValueFormat, color: str | None = None) -> dict
def recon_bridge(recon: ReconResult) -> dict

# app/ (FastAPI api.py):   calls only sherpa.pipeline.answer(...), sherpa.config.load_access/load_catalog,
#                          sherpa.runs.recent_runs/run_series/run_stats/history/get_run/save_feedback, sherpa.charts,
#                          and reads eval/results/latest.json
# app/overview.py (home):  sherpa.compiler.compile_metric -> sherpa.db.run_query as the persona (the governed path:
#                          guard, RLS, cost gate); no LLM, no app.runs write; cached per (persona, data_version).
#                          data_health (GET /api/data-health): compile_dq_queries -> run_query -> sherpa.dq.run_checks,
#                          same path and cache key
# web/ (Next.js):          talks only to app/api.py over HTTP; every number it shows is a string from app/view.py
```

## 6. master (integration)

```python
# sherpa/pipeline.py
def answer(question: str, persona: str, *, plan: AnalysisPlan | None = None,
           on_stage: Callable[[str], None] | None = None,    # on_stage(name): plan, triage, analysis, dq, narrate, check
           on_partial: Callable[[AnswerBundle], None] | None = None) -> AnswerBundle
#   on_partial(copy): once, after analysis and dq, before narrate; a deep copy with evidence, drivers/recon, dq, plan
#   and route but no headline, claims or confidence. A raising callback (like on_stage) never breaks the run.
#   plan given (Explore mode or a clarification choice): skip the planner.
#   Never raises; failures become status="error" with a message. Always save_run().
```

## 7. Eval output (wave 2), `eval/results/latest.json`

```json
{"generated_at": "...", "data_version": "...", "systems": {
   "sherpa":   {"result_equivalence": 0.0, "planted_causes": 0.0, "refusals": 0.0, "clarifications": 0.0,
                "unsupported_numbers": 0, "p50_ms": 0, "cost_usd": 0.0},
   "baseline": {"...same keys..."}},
 "cases": [{"id": "...", "kind": "...", "question": "...", "expected": {}, "sherpa": {"pass": true, "detail": "..."},
            "baseline": {"pass": false, "detail": "..."}}]}
```
