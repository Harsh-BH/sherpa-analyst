# Task DAG and tracker

Owner: master. Agents report status in `../sherpa-analyst.worktrees/_coord/<agent>.status`, and the master folds it in here.
Status values: Pending · Ready · In Progress · Blocked · In Review · Completed.

## Agents

| tmux session | branch / worktree | scope |
|---|---|---|
| `master` | `main` (this checkout) | contracts, integration (`pipeline.py`), review, merges, eval run, docs |
| `data` | `feature/data` | compose, Makefile, generator + planted causes, analytics build, roles/RLS |
| `sql` | `feature/sql` | guard, compiler, executor, run log |
| `analytics` | `feature/analytics` | rate/mix drivers, DQ, reconciliation → wave 2: eval harness |
| `ai` | `feature/ai` | LLM backends, planner, triage, narrator + claim checker |
| `ui` | `feature/ui` | Streamlit app, charts, fixtures |

## DAG

```
F1 skeleton ─┬─ F2 contracts ─┬─ Q1 guard ───────────┐
             │                ├─ Q2 compiler ────────┤
             │                ├─ A1 decompose ─ A2 explain_change/drill ─┐
             │                ├─ A3 dq   A4 reconcile ┤                   │
             │                ├─ L1 llm ─ L2 planner ─┤                   │
             │                ├─ L3 triage   L4 narrate/check/confidence ─┤
             │                └─ U1 fixtures ─ U2 charts ─ U3 Ask ─ U4 Explore ─ U5 Eval/Runs
             └─ F3 schema+db up ─ D4 roles/RLS ─┬─ Q3 executor ─ Q4 runs ─ Q5 db tests
                                  D1 generator ─┴─ D2 scenarios ─ D3 analytics build ─ D6 data tests
                                                                     │
   I1 pipeline.answer  ◀── Q2,Q3,A2,A3,A4,L2,L3,L4,U2 ───────────────┘   (critical path: F3→D1→D2→D3→I2→I4)
   I2 merge wave 1 + e2e tests ─ I3 UI on real pipeline (ui) ─ I4 eval harness + baseline (analytics, wave 2)
   I5 adversarial review (workflow) + fixes ─ I6 README/demo/compose verify ─ I7 final report
```

Start immediately (no DB needed): Q1, Q2, A1–A4, L1–L4, U1–U5, D4, D1. Need a seeded DB: Q3 calibration, Q5, D6, the A real-data check.

## Tracker

| ID | Task | Agent | Deps | Prio | Cx | Status |
|---|---|---|---|---|---|---|
| F1 | repo skeleton, pyproject, uv.lock, .env, CLAUDE.md | master | – | P0 | S | Completed |
| F2 | contracts.py, config.py, catalog.yaml, access.yaml, CONTRACTS.md | master | F1 | P0 | M | Completed |
| F3 | schema.sql, compose db up | master | F1 | P0 | S | Completed |
| F4 | briefs, worktrees, tmux agents | master | F2,F3 | P0 | S | Completed |
| D1 | generator core, calibrated | data | F3 | P0 | L | Completed |
| D2 | planted scenarios + ground_truth.json | data | D1 | P0 | L | Completed |
| D3 | build_analytics.sql | data | D1 | P0 | M | Completed |
| D4 | roles/grants/RLS from access.yaml | data | F3 | P0 | M | Completed |
| D5 | Makefile, compose app, Dockerfile | data | F1 | P1 | S | Completed |
| D6 | data tests (determinism, RLS, grants, truth) | data | D2–D4 | P0 | M | Completed |
| Q1 | guard + attack corpus | sql | F2 | P0 | M | Completed |
| Q2 | compiler + windows | sql | F2 | P0 | M | Completed |
| Q3 | executor, cost gate, cache | sql | D4 | P0 | M | Completed |
| Q4 | runs log | sql | D4 | P1 | S | Completed |
| Q5 | db tests | sql | D3,D4 | P0 | M | Completed |
| A1 | decompose + stats | analytics | F2 | P0 | M | Completed |
| A2 | explain_change, ranking, Adtributor, drill, evidence | analytics | A1 | P0 | L | Completed |
| A3 | dq checks | analytics | F2 | P1 | S | Completed |
| A4 | reconcile | analytics | F2 | P1 | S | Completed |
| L1 | llm backends | ai | F1 | P0 | M | Completed |
| L2 | planner | ai | L1,F2 | P0 | M | Completed |
| L3 | triage | ai | F2 | P0 | M | Completed |
| L4 | narrate, check_claims, confidence, template | ai | L1,F2 | P0 | L | Completed |
| U1 | fixtures | ui | F2 | P1 | S | Completed |
| U2 | charts | ui | F2 | P1 | M | Completed |
| U3 | Ask page | ui | U1,U2 | P0 | L | Completed |
| U4 | Explore mode | ui | U3 | P1 | M | Completed |
| U5 | Eval + Runs pages | ui | U3 | P2 | S | Completed |
| I1 | pipeline.answer | master | Q2,Q3,A2–A4,L2–L4,U2 | P0 | L | Completed |
| I2 | merge wave 1, e2e tests | master | all wave 1 | P0 | M | Completed |
| I3 | UI on real pipeline, demo dates | ui | I1 | P0 | S | Completed |
| I4 | eval harness, 2 seeds, naive baseline | analytics | I1,D2 | P0 | L | Completed |
| I5 | adversarial review workflow + fixes | master | I2 | P0 | M | Completed |
| I6 | README, demo script, full compose verify | master | I3,I4,I5 | P0 | M | Completed |
| I7 | final report, push | master | I6 | P0 | S | Completed |

## Final state

- 391 tests pass (3 live-LLM tests deselected by default). Fresh two-seed eval on `2f13f1c`: Sherpa 56/56, naive baseline 17/56, unsupported numbers 0 vs 72.
- Docker app image built and verified (health + pipeline inside the container), then removed to free disk.

## Adversarial review (I5): 24 findings, all reproduced by an independent skeptic, all fixed with regression tests

Four reviewers (guard, RLS, compiler, analytics), each followed by a skeptic that had to reproduce the finding. R1 was also hardened in the DB by data (REVOKE EXECUTE).

| # | Sev | Finding | Fixed by |
|---|---|---|---|
| R1 | high | Function and table allowlist bypassed by field-selection syntax: (expr).fname runs fname(expr), including arbitrary dyna | sql |
| R2 | high | Result size in bytes is unbounded: a window string_agg makes each of the 5,001 allowed rows several MB, and psycopg buff | sql |
| R3 | medium | LIMIT bypass: FETCH FIRST n ROWS WITH TIES is kept, so the entire table is shipped to the app | sql |
| R4 | medium | EXPLAIN cost gate reads the top Limit node's pro-rated cost, so runaway joins that return rows pass the gate | sql |
| R5 | low | check_sql raises RecursionError (not QueryRejected) for 47 nested parentheses | sql |
| R6 | low | Result cache key omits max_rows: a truncated result is served to a later call with a larger max_rows | sql |
| R7 | medium | analytics.data_version.row_count shows the all-region transaction count to rm_south through the guarded path | master |
| R8 | medium | Persona and app roles can write persistent large objects in every database they can connect to (read-only is only a defa | data |
| R9 | low | Persona can persistently rewrite its own role config (password, row_security, per-DB read_only); roles.py does not reset | data |
| R10 | low | TEMP and CONNECT are revoked only on the target DB: personas and the app role can create temp tables and functions in po | data |
| R11 | low | Planner statistics (EXPLAIN row estimates, pg_class.reltuples) reveal per-region volume to rm_south | master (doc: known limit) |
| R12 | low | A persona removed or renamed in access.yaml keeps LOGIN and its analytics grants after re-running roles.py | data |
| R13 | high | Default baseline is clamped to a shorter span but still labelled 'same length', so GMV 'last month' shows a 31-day vs 10 | master |
| R14 | medium | Overlapping window and baseline: overlap rows count only as 'current', which shrinks or empties the baseline | sql |
| R15 | high | Pipeline ignores QueryResult.truncated, so breakdowns and trends over 5,000 rows silently drop the alphabetically last g | master |
| R16 | medium | explain_change on any settlement metric always errors: the default dimension payment_method does not exist on settlement | master |
| R17 | low | Hourly grain on gmv_settlement_basis pairs cycle_date with txn_hour, so the 'D 23:00' bucket is really D-1 23:00 | sql |
| R18 | medium | No significance or size gate on the change: explain_change names a top driver and raises the Simpson flag when the move  | analytics |
| R19 | medium | Simpson flag ignores which way mix moved: it fires when mix pushed the rate the opposite way to Δ | analytics |
| R20 | medium | For ratio metrics with a summed numerator (avg_ticket_size), segments are never tested, so the Simpson flag reduces to ' | analytics |
| R21 | medium | Gap check's fixed 20-attempt floor shortens the planted PG_C outage for South-scoped views (reports 07:00-08:00 instead  | analytics |
| R22 | medium | Multi-day outage: the 7-day median baseline counts the outage's own days, so detection stops after 4 days and the messag | analytics |
| R23 | low | Gap check silently skips the first day of data and judges the second day against a single day | analytics |
| R24 | low | Adtributor port leaves out the paper's T_EP stopping rule, so 'most surprising dimension' can differ from Adtributor | analytics |
