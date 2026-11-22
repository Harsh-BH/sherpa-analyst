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

## UI rebuild: Next.js Inspector Rail (branch `feature/nextjs-ui`)

Streamlit replaced by a Next.js front end over a FastAPI service. Spec: `docs/superpowers/specs/2026-11-21-nextjs-inspector-ui-design.md`;
plan: `docs/superpowers/plans/2026-11-21-nextjs-inspector-ui.md`.

| ID | Task | Agent | Deps | Prio | Cx | Status |
|---|---|---|---|---|---|---|
| W1 | view model `app/view.py`: every number a string | ui | I7 | P0 | M | Completed |
| W2 | FastAPI `app/api.py`: ask over SSE, meta, explore, eval, runs | ui | W1 | P0 | M | Completed |
| W3 | web scaffold, theme, shell, API client, e2e harness | ui | W2 | P0 | M | Completed |
| W4 | Ask page, live trace, answer view | ui | W3 | P0 | L | Completed |
| W5 | inspector rail, linked selection, themed charts | ui | W4 | P0 | L | Completed |
| W6 | clarification, refusal and error states; Explore | ui | W5 | P1 | M | Completed |
| W7 | Eval and Runs pages | ui | W4 | P2 | S | Completed |
| W8 | Streamlit removed; Docker files written (not built: disk); docs; live check | ui | W6,W7 | P1 | S | Completed |
| W9 | merge to `main` with `--no-ff`, push | master | W8 | P0 | S | Completed (`148b4ad`) |

## UI polish (branch `feature/ui-polish`, merged as `2738e69`)

| ID | Task | Commits | Status |
|---|---|---|---|
| P1 | label every run by source (`app.runs.source` from `SHERPA_RUN_SOURCE`); Runs shows app runs only | `99a8cac` | Completed |
| P2 | stage timing fractions, and a step count that matches the trace | `a310a98` | Completed |
| P3 | `GET /api/overview` (30 days vs the 30 before, governed path) and Eval/Runs chart specs | `9be2cdf` | Completed |
| P4 | accent theme with AA contrast in light and dark; CSS-only motion, off under reduced motion | `49cb881` | Completed |
| P5 | home KPI cards and trend, Eval and Runs charts, status badges, trace timing bars | `fc3ad22` | Completed |
| P6 | review fixes: chart ticks and labels, AA badges on selected rows, sticky headers, steady skeleton | `e6cc3c7` `69159c0` `3ff6f0b` `5b1fb64` | Completed |

## UX pack (branch `feature/ux-pack`, merged as `adaada0`)

Five agents, one worktree each, built twelve features in parallel; an integrator merged them, and review agents checked the result.

| ID | Track | Feature | Commits | Status |
|---|---|---|---|---|
| X1 | ux-history | run history, `/?run=` permalinks, thumbs feedback (`app.runs.bundle`, insert-only `app.run_feedback`), sidebar Recent | `4531da4` `c012e08` | Completed |
| X2 | ux-stream | SSE `partial` event: chart, DQ banners and tables before the narrative | `d28d566` `23bb129` | Completed |
| X3 | ux-home | explain a dip (click a trend day), unusual days, data-health rail, eval proof line | `abba9b1` `3c24450` | Completed |
| X4 | ux-answer | Ask next follow-ups, waterfall drill-down, copy answer (Markdown), chart PNGs, headline chips, key columns | `1f675f1` `ad49f51` | Completed |
| X5 | ux-shell | command palette (⌘K / Ctrl K, `/`), phone layout with a bottom-sheet rail, 40 px tap targets | `26993c6` | Completed |
| X6 | integrator | merge the five tracks; the palette's Recent group reads run history | `434b40d`…`bfee191` `bd6757f` | Completed |
| X7 | review fixes | bare 404s on run endpoints, follow-up wording, partial-to-result swap, PNG for every chart, phone tap targets, More columns label from Python, time-axis label spacing | `af1feee`…`7ffc8d4` | Completed |
| X8 | master | one date label a week on the home trend, so labels never overlap on a narrow card | `650000b` | Completed |
| X9 | master | merge to `main` with `--no-ff`, push | `adaada0` | Completed |
| X10 | master | README and docs refresh (features, screenshots, test counts, demo script) | branch `docs/submission-refresh` | Completed |

## Final state (22 Nov 2026)

- **Tests:** 455 Python tests pass (3 live-LLM tests deselected by default) and 85 browser tests pass.
- **Eval:** a fresh two-seed run on 21 Nov (committed in `8ce761b`) gave Sherpa 56/56 and the naive baseline 17/56, with
  unsupported numbers 0 vs 72. Later rounds changed the UI, the API, run storage and chart styling, not the analysis path.
- **Docker:** the Python image was built and verified with the Streamlit UI (health plus a pipeline answer inside the
  container), then removed to free disk. The `api` and Next.js `web` images are written but not built.
- **Submitted on 22 Nov 2026:** the repo was made public for review, and the [demo video](https://drive.google.com/file/d/18nPHNoJEuswhhqcJ9p4BTKEN5-DaiPhA/view) (4:42) is linked from the README.

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
