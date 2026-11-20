# Brief: analytics agent (driver engine, data quality, reconciliation; later the eval harness)

This is the part that should make a reviewer stop: the honest answer to "why did success rate drop?",
including when the honest answer is "nothing got worse; the mix changed".

**You own:** `sherpa/drivers.py`, `sherpa/dq.py`, `sherpa/reconcile.py`, `tests/test_drivers.py`,
`tests/test_dq.py`, `tests/test_reconcile.py`, and later `eval/` (wave 2, briefed separately).
Signatures: docs/CONTRACTS.md §3. Types: `sherpa/contracts.py`. Thresholds: constants in `sherpa/config.py`.
Everything is pure pandas, with no DB, so you can start immediately.

## Tasks

**A1: `drivers.decompose`.** The symmetric rate/mix split is in docs/ARCHITECTURE.md.
- **Missing segments:** a segment present in one period only takes the other period's rate, so its whole effect is mix.
- **Invariant:** assert `|Σmix + Σrate − Δ| < 1e-12`.
- **Per-segment test:** two-proportion z (statsmodels `proportions_ztest`) for ratio metrics whose numerator is a count. For sum-based numerators (avg_ticket_size), no z-test: leave z, p and q as None and `significant=False`.
- **Mix test:** chi-square on the share table (scipy `chi2_contingency`).
- **Flags:** `supported` and `material` per the thresholds.
- **Simpson flag** for the dimension: |mix_total| ≥ SIMPSON_MIX_SHARE·|Δ| and no supported segment whose rate moved significantly in the same direction as Δ. `significant` needs q-values, so a standalone `decompose` uses raw p as a stand-in, and `explain_change` recomputes it after BH.
- **Tests:**
  - **the worked example** (Cards 60k@96.0% → 40k@96.5%; UPI 40k@88.0% → 60k@88.5%): Δ = −1.10 pp, mix −1.60 pp, rate +0.50 pp, Simpson flag true.
  - a segment appearing only in current
  - a zero-denominator segment
  - an invariant property test on random frames (numpy seeded, 200 cases)

**A2: `drivers.explain_change` + `drilldown` + `evidence_from_report`.**
- BH (statsmodels `multipletests(method="fdr_bh")`) across all segment tests in the report.
- **Ranking:** define `score` so that the dimension that best *explains* the change ranks first, and document the rule in the docstring. Two cases must hold:
  - **(a) a localised rate break:** one bank's rate collapses. issuer_bank must outrank payment_method, even though the method that bank serves also dips.
  - **(b) a pure mix shift:** per-method rates are flat while UPI share rises. payment_method (or the correlated merchant_category) ranks first, with the Simpson flag.

  Build both as synthetic multi-dimension frames, generated from one row-level synthetic DataFrame so the dimensions are mutually consistent, and test them.
- **Adtributor cross-check** per dimension: explanatory power and surprise (JS divergence) for derived (ratio) measures.
  - Port the formulas from `shaido987/riskloc` (MIT). Read the actual source: `gh api repos/shaido987/riskloc/contents/...`, or clone into `/tmp/claude-1001/riskloc`.
  - Attribute it in a comment, cite Bhagwan et al., NSDI 2014, and don't vendor anything else.
  - Record in `notes` whether the Adtributor top segment agrees with the decomposition's top segment.
- **Drill-down** of the top (d1, d2) pairs supplied by the caller: decompose with segment = "d1=v1 · d2=v2" and return the top cells. Test: an issuer×network break invisible at depth 1 but clear at depth 2.
- **`evidence_from_report`:** one Evidence for the overall comparison (r0, r1, delta, mix_total, rate_total with formats), one per top-3 dimensions (per-segment shares, rates, effects; keys like `UPI_share1`, `UPI_rate_effect`), and one for the drill-down. Keys must be valid placeholder keys: `[A-Za-z0-9_]+`. Sanitize segment values into keys deterministically and keep a mapping in `table`.

**A3: `dq.run_checks`.**
- **duplicates:** a day×gateway with duplicate_events ≥ 100 or ≥ 0.5% of events is a `warn`, worded "removed by deduplication".
- **missing_data:** in `hourly`, compare each (date, hour, gateway) in the window with the median of the same hour and gateway over the preceding 7 days. Attempts below 10% of that median is a gap. Merge consecutive gap hours into one `error` with the range ("PG_C has no data on 16 Nov 02:00–08:00 IST").
- **nulls:** `null_issuer_nonwallet > 0` is a `warn`.
- **freshness:** a window end beyond `as_of` is a `warn`.
- Messages are code-generated, so numbers are allowed in them. Test each check, including a clean window that yields no warnings.

**A4: `reconcile.reconcile`.** Per CONTRACTS.md §3, with the identity asserted and component notes in plain English ("Sales after 23:00 IST on 12 Nov settle in the next cycle"). Test with hand-built frames, including a missing-transactions case.

## Acceptance
- `uv run pytest tests/test_drivers.py tests/test_dq.py tests/test_reconcile.py` pass, with the worked example exact to 1e-9.
- Once the data agent has seeded (watch `$COORD/data.status`), run your functions on real DB frames for S1 and S2 using a scratch script (build the frames with plain psycopg as admin; nothing is committed). Put the top dimension, the Simpson flag and the top segments for both in your report. **If the ranking gets either wrong on real data, fix it before reporting done.**
