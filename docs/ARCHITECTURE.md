# Sherpa architecture

Pine Labs "First Prompt" case 02: **Enterprise AI Business Analyst**. The brief asks for NL questions over
≥2 related payments datasets, generated and executed SQL, visible steps, charts and tables, citations
(dataset, filters, window), and facts kept separate from hypotheses and recommendations. It names these
failure cases: missing or duplicate records, out-of-scope access, two sources disagreeing, **a decline
explained by mix shift**, an ambiguous period or denominator, and an expensive or unsafe query.

## Principle

**The LLM translates and narrates; deterministic code computes.** The model never invents a number and
never sees row-level data.

```
 persona ─▶ Next.js UI ─▶ FastAPI: Ask | Explore | Eval | Runs
                │ question, persona                                  ▲ AnswerBundle
        ┌───────▼────────┐  AnalysisPlan   ┌───────────────────┐      │
        │ planner (LLM)  ├───────────────▶ │ triage             ├─ clarify / explained refusal ─▶ UI
        │ catalog + VQs  │                 │ names·scope·ambig. │
        └────────────────┘                 └─────────┬─────────┘
   Explore picker (no LLM) ── same AnalysisPlan ─────┤
                     ┌───────────────────────────────▼──────────────────────────┐
                     │ compiler (catalog → SQL)   │  LLM SQL (route "sql")       │
                     └───────────────────────────────┬──────────────────────────┘
       guard: parse()==1 stmt · SELECT root · no DML/DDL/SET/INTO/locks · fn allowlist
              · tables+columns ⊆ access.yaml (sqlglot qualify) · LIMIT
       db:    persona's DB role · READ ONLY · SET LOCAL statement_timeout · EXPLAIN cost gate · ROLLBACK
                     ┌───────────────────────────────▼──────────────────────────┐
                     │ drivers (rate/mix + z/BH + Adtributor + drill) · dq · reconcile │
                     └───────────────────────────────┬──────────────────────────┘
                              Evidence[] (id, sql, window, filters, values, chart)
                     narrator (LLM, sanitized aggregates) → claims with {E#.key} placeholders
                     claim checker (no free numerals, facts cite evidence) + confidence → app.runs → UI
```

Routes: **catalog** = governed metric compiled to SQL (trusted). **sql** = LLM-written SELECT against
`analytics.*`, labelled "unverified", confidence capped at medium, and sent through the same guard.

## UI layer

The browser never calls the pipeline. `web/` is a Next.js app that proxies `/api/*` to `app/api.py`, a FastAPI service
on `127.0.0.1:8000`:

- **Ask streams.** `POST /api/ask` runs `pipeline.answer()` in a worker thread and sends one SSE `stage` event per
  `on_stage` call, then a `result` event with the `AnswerBundle` and its view. The proxy runs uncompressed so stages
  arrive as they happen, and the trace shows each one with its elapsed time.
- **Numbers are formatted once, in Python.** `app/view.py` turns the bundle into display strings with `format_value`;
  the front end never computes or formats a number, so the screen cannot disagree with the bundle.
- **Data stays inert.** Data-derived text renders only as React text nodes, with no raw HTML and no URLs built from data.
  Data-quality banners sit above the headline and are never collapsed.
- **Charts** are the `sherpa/charts.py` Vega-Lite specs drawn by vega-embed. Their colours are remapped per theme through
  `web/lib/chart-colors.json`, and a test fails if `charts.py` emits a colour the map does not cover.
- **Layout:** a sidebar (persona, pages, data version, LLM backend), the answer in the centre, and an inspector rail
  (Plan · Evidence · Footprints). Selecting an evidence chip opens its rail entry and highlights every claim that cites it.
- **Fixture mode:** `SHERPA_UI_FIXTURES=1` makes the API answer from `tests/fixtures/`; the Playwright suite in
  `web/e2e/` runs against it.

## Safety in two layers

1. **App layer (explains):** `guard.check_sql` produces readable refusals. Triage refuses out-of-scope
   requests *before* any SQL runs and offers what the persona can see.
2. **DB layer (enforces):** each persona has its own login role with column-level GRANTs on `analytics.*`
   only, `ENABLE + FORCE ROW LEVEL SECURITY` on region, and read-only sessions. Even if the app layer
   has a bug, rows outside scope cannot come back.

Both layers are generated from `db/access.yaml`, and a test asserts they match.

## Driver engine (explain_change)

For a ratio metric R = S/N per segment i, with share c = n/N and rate r = s/n, over baseline (0) and current (1):

```
ΔR = Σ_i (c1_i − c0_i)·((r0_i + r1_i)/2 − R̄)      mix_i    (R̄ = (R0 + R1)/2)
   + Σ_i (r1_i − r0_i)·(c0_i + c1_i)/2            rate_i
```

The two sums add up to ΔR exactly (Kitagawa 1955; Das Gupta 1993), with no leftover interaction term. A
segment absent in one period takes the other period's rate, so its whole contribution is mix. Each
segment also gets a two-proportion z-test, with Benjamini–Hochberg across the report. Reporting gates
are support (n ≥ 1,000 in both periods, ≥ 1% share) and materiality (|Δr| ≥ 0.3 pp, ≥ 5% of |ΔR|).
**Simpson flag**: |Σmix| ≥ 50% of |ΔR| and no supported segment's rate moved significantly in the
direction of ΔR. Adtributor explanatory power and surprise give a cross-check, and a depth-2 drill-down
covers the top dimension pairs.

Worked example (a unit test): Cards 60%→40% of volume at 96.0%→96.5%, UPI 40%→60% at 88.0%→88.5%.
Overall 92.8%→91.7% (ΔR −1.10 pp) = mix −1.60 pp + rate +0.50 pp.

## Synthetic data with planted causes

No public dataset has bank, method and decline-type fields (PaySim has none), so `gen/generate.py`
produces 60 days (2026-09-21 to 2026-11-19 IST), ~25k attempts/day, calibrated to NPCI-like levels.
The baseline success rate excluding drop-offs is about 88.5% for UPI and about 96% for cards. It plants
known causes and writes `data/ground_truth_<seed>.json`:

| id | scenario | what it exercises |
|---|---|---|
| S1 | UPI-heavy merchant onboards on as_of−6; UPI share of attempts rises ~45%→~58%; per-method rates flat | mix shift / Simpson |
| S2 | one bank (seeded) has a technical-decline spike (~25%) 10:00–16:00 IST on one day (seeded, Oct 20–Nov 2) | rate effect, localised |
| S3 | one issuer × one card network (seeded) fails 3DS (~40%) 14:00–20:00 on one day | depth-2 drill-down |
| S4 | settlements with 23:00 IST cutoff, T+1, refunds ~0.2%, MDR 1.8% | two sources disagree |
| S5 | ~1,200 duplicate webhook events on PG_B (one day); PG_C ingests nothing on as_of−3 02:00–08:00 | data-quality warnings; recon residual |
| S6 | a merchant display_name carrying a prompt injection | injection containment |

Scenario parameters are drawn from the seed. The eval runs on two seeds, so tuning to one seed shows up.

## Personas

`head` sees all regions. `rm_south` sees South only, and asking about North gets an explained refusal
plus a South-only offer; the DB backstop is tested separately.

## Known limits (be honest in README)

- **Planner statistics are not row data, but they leak volume.** RLS hides rows, not `pg_class.reltuples` or EXPLAIN row
  estimates, so a scoped persona with a direct DB login could infer per-region volume. Personas never get direct logins; the app
  holds the credentials. A real fix needs per-region tables or partitions (review R11).

Decomposition is association, not causation; cause mappings are always tagged *hypothesis*. The eval is
partly circular, since we plant what we detect; mitigations are randomised parameters, two seeds and
a naive baseline on the same data. Catalog coverage bounds the trusted route.
