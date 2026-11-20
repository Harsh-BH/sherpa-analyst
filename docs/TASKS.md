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
| F4 | briefs, worktrees, tmux agents | master | F2,F3 | P0 | S | In Progress |
| D1 | generator core, calibrated | data | F3 | P0 | L | Ready |
| D2 | planted scenarios + ground_truth.json | data | D1 | P0 | L | Pending |
| D3 | build_analytics.sql | data | D1 | P0 | M | Pending |
| D4 | roles/grants/RLS from access.yaml | data | F3 | P0 | M | Ready |
| D5 | Makefile, compose app, Dockerfile | data | F1 | P1 | S | Ready |
| D6 | data tests (determinism, RLS, grants, truth) | data | D2–D4 | P0 | M | Pending |
| Q1 | guard + attack corpus | sql | F2 | P0 | M | Ready |
| Q2 | compiler + windows | sql | F2 | P0 | M | Ready |
| Q3 | executor, cost gate, cache | sql | D4 | P0 | M | Ready (calibration waits on D3) |
| Q4 | runs log | sql | D4 | P1 | S | Ready |
| Q5 | db tests | sql | D3,D4 | P0 | M | Pending |
| A1 | decompose + stats | analytics | F2 | P0 | M | Ready |
| A2 | explain_change, ranking, Adtributor, drill, evidence | analytics | A1 | P0 | L | Pending |
| A3 | dq checks | analytics | F2 | P1 | S | Ready |
| A4 | reconcile | analytics | F2 | P1 | S | Ready |
| L1 | llm backends | ai | F1 | P0 | M | Ready |
| L2 | planner | ai | L1,F2 | P0 | M | Pending |
| L3 | triage | ai | F2 | P0 | M | Ready |
| L4 | narrate, check_claims, confidence, template | ai | L1,F2 | P0 | L | Pending |
| U1 | fixtures | ui | F2 | P1 | S | Ready |
| U2 | charts | ui | F2 | P1 | M | Ready |
| U3 | Ask page | ui | U1,U2 | P0 | L | Pending |
| U4 | Explore mode | ui | U3 | P1 | M | Pending |
| U5 | Eval + Runs pages | ui | U3 | P2 | S | Pending |
| I1 | pipeline.answer | master | Q2,Q3,A2–A4,L2–L4,U2 | P0 | L | Pending |
| I2 | merge wave 1, e2e tests | master | all wave 1 | P0 | M | Pending |
| I3 | UI on real pipeline, demo dates | ui | I1 | P0 | S | Pending |
| I4 | eval harness, 2 seeds, naive baseline | analytics | I1,D2 | P0 | L | Pending |
| I5 | adversarial review workflow + fixes | master | I2 | P0 | M | Pending |
| I6 | README, demo script, full compose verify | master | I3,I4,I5 | P0 | M | Pending |
| I7 | final report, push | master | I6 | P0 | S | Pending |
