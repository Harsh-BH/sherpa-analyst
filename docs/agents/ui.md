# Brief: ui agent (Streamlit app + charts)

The reviewer's first 60 seconds happen here. The page must make the evidence trail obvious: each claim
has a tag (Fact / Hypothesis / Recommendation / Caveat), a click opens the SQL, window and filters behind
it, the chart sits next to it, and data-quality warnings and confidence reasons can't be missed.

**You own:** `app/` (Streamlit entry `app/streamlit_app.py` + any `app/*.py` helpers), `sherpa/charts.py`,
`.streamlit/config.toml`, `tests/fixtures/`, `tests/test_charts.py`, `tests/test_app.py`.
Signatures: docs/CONTRACTS.md §5. Types: `sherpa/contracts.py`.
`sherpa/pipeline.py` does not exist yet; the master writes it after wave 1. Build against **fixture
AnswerBundles** until then.

## Tasks

**U1: fixtures.** `tests/fixtures/make_bundles.py` builds and validates AnswerBundle JSON files with pydantic:
- `explain_change.json`: the worked Simpson example. Cards 60%→40% at 96.0→96.5, UPI 40%→60% at 88.0→88.5; the DriverReport with a payment_method decomposition; 5 claims across all 4 kinds; a DQ warn for PG_C missing hours; confidence medium with reasons; 3 evidence items with SQL.
- `clarify.json`: a denominator ambiguity with 2 options showing previews.
- `refused.json`: rm_south asking about North.
- `sql_route.json`: an unverified-SQL answer.
- `reconcile.json`: a ReconResult with the components.

Write the files and commit them. They are also the UI's offline demo data.

**U2: `sherpa/charts.py`.** Vega-Lite v5 dicts.
- `waterfall`: one bar per top segment for mix and for rate (color-coded, with a legend), plus total bars for overall mix, rate and Δ; axis in pp.
- `bars` and `trend` with axis formats by `ValueFormat`.
- `recon_bridge`: a bridge from txn GMV to settled net.
- **Style:** colorblind-safe palette, titles, tooltips, readable at 700 px width, and no reliance on color alone (labels on bars).
- **Tests:** specs are valid dicts with expected encodings, built from the fixtures.

**U3: the Ask page.**
- **Sidebar:** persona selector (from `load_access()`; label + regions); data version and as_of (from the bundle once one exists); LLM backend in use; mode radio Ask / Explore / Eval / Runs.
- **Input:** example question chips (catalog verified queries plus the five demo questions: "Why did success rate drop last week?", "Why did success rate fall on <S2 date>?", "Card success rate fell on <S3 date>: what drove it?", "Why doesn't settled amount match GMV for <S4 date>?", "Compare North vs South success rate" (as rm_south)). The scenario dates come later from the ground truth; use placeholders now.
- **Answer card:**
  - the headline
  - a confidence badge with expandable reasons
  - a route label: "Governed metric", or "Unverified SQL" with a warning style
  - assumptions listed
  - claims grouped by kind with colored tags, each showing its evidence ids as buttons or expanders
- **Evidence panel:** per Evidence, the title, window/baseline, filters, row count, tables used, SQL in `st.code(..., language="sql")` with its hash, the result table (`st.dataframe`), and the chart (`st.vega_lite_chart`).
- **Driver section** when `drivers` is present: the waterfall plus a Simpson callout explaining it in one sentence; the segment table with shares, rates, effects and significance; drill-down cells.
- **DQ warnings:** a banner at the top of the answer, with severity colors.
- **Clarification:** option buttons with previews. Choosing one calls `answer(question, persona, plan=patched_plan)`.
- **Refusal:** a card with the reason and suggestion; a button applies the suggested plan.
- **Downloads:** "Download run bundle" (AnswerBundle JSON).
- **Errors:** an error card that keeps the run id.
- **Security:** render every data-derived string as plain text. Never `unsafe_allow_html=True` with data in it (merchant names can contain injection text).

**U4: Explore mode.** Pickers for intent, metric (labels from the catalog), dimensions (filtered to the metric's table), filters (dimension + values multiselect from vocabularies), window and baseline presets, and grain. These build an `AnalysisPlan(route="catalog", ...)` and call `answer(question=<generated description>, persona, plan=plan)`. Show the plan JSON in an expander.

**U5: Eval and Runs pages.**
- **Eval** reads `eval/results/latest.json` (schema in CONTRACTS.md §7; make a fixture). It shows a scorecard of Sherpa vs the baseline as metric tiles plus a per-case table with pass/fail and detail.
- **Runs** shows `sherpa.runs.run_stats()` tiles (p50/p95 latency, cost, refusal/clarify/cache rates) and a `recent_runs()` table. Guard both pages with try/except so the page renders with a clear message when the DB or file is absent.

**Dev mode until the pipeline exists:** if `import sherpa.pipeline` fails, or `SHERPA_UI_FIXTURES=1`, `answer()` returns the fixture bundle that best matches the question (keyword match), and a small banner says "fixture mode". Keep this switch in one function in `app/`.

**Tests:** `tests/test_app.py` uses `streamlit.testing.v1.AppTest` in fixture mode. Assert the app renders, without exceptions, for each fixture and each mode, that claims show their kind tags, that SQL code blocks are present, and that an injection string in a fixture's evidence table is rendered as text.

## Acceptance
- `SHERPA_UI_FIXTURES=1 uv run streamlit run app/streamlit_app.py --server.headless true --server.port 8601` serves without errors.
- Take a screenshot of the Ask page with the explain_change fixture: use headless Chrome, e.g. `google-chrome --headless=new --screenshot=/tmp/claude-1001/ui-ask.png --window-size=1400,2200 http://localhost:8601` (check which Chrome binary exists), and look at it. Include the path in your report.
- Stop the streamlit server when done.
- All tests pass.
