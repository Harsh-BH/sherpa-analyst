# Next.js front end, "Inspector Rail": design

Status: draft for Harsh's approval · 2026-11-21 · branch `feature/nextjs-ui`

## Intent

Replace Sherpa's Streamlit UI with a Next.js front end in the **Inspector Rail** direction. Harsh chose it from three
researched options; the mockups and sources are at https://claude.ai/artifact/DCKBR5HTy7VGnggp8rTCAX (private).

Why this direction: Sherpa's claim is that every number can be traced and every guess is labelled. Inspector Rail
keeps the proof (SQL, window, filters, row counts, query hash) on screen beside the claim it supports, so the claim
is visible in every screenshot, not just asserted. Harsh has not said why he is moving off Streamlit; the working
assumption is a product-grade first impression for the Pine Labs reviewers and the demo video.

## Goals

1. **Parity with every Streamlit screen and state.** No current behaviour is lost:
   - **Ask:**
     - question box;
     - demo-question chips, including the refusal demo that switches the persona to `rm_south`;
     - verified-question chips from the catalog;
     - deep link `/?q=…&persona=…`, which asks once on load and ignores unknown personas.
   - **Answer:** in this order:
     - data-quality banners;
     - headline;
     - confidence and route badges ("Governed metric" or "Unverified SQL");
     - the unverified-SQL warning;
     - footprint line;
     - "why this confidence";
     - assumptions;
     - claims with kind tags and evidence chips;
     - key chart with a "Decompose by" dimension picker, Simpson callout and driver notes;
     - driver tables;
     - reconciliation components with the source of truth;
     - evidence (titles, tables, charts, SQL, meta);
     - download of the run bundle.
   - **Clarification:** the options with their previews; choosing one answers the question.
   - **Refusal:** the reason, the suggestion, and a one-click alternative that runs.
   - **Error:** an error card that keeps the run id.
   - **Explore:** the hand-built plan form, the question text and plan preview, and Run.
   - **Eval:** Sherpa vs baseline tiles, the cases table, and the fixture-mode notice.
   - **Runs:** stats tiles and the recent-runs table.
   - **Sidebar:** data version, as-of date, the LLM backend, and the fixture-mode notice.
2. **Inspector Rail layout** as in mockup B:
   - **Left sidebar:** collapses to an icon rail.
   - **Centre:** the question bar and the answer.
   - **Right rail:** tabs **Plan · Evidence (n) · Footprints**.
   - **Selection linked both ways:** clicking an evidence chip opens that entry in the rail and highlights every claim that cites it; selecting a rail entry does the same.
   - **Narrower screens:** below 1280 px wide the rail becomes a slide-over sheet; on phones the sidebar becomes a top bar.
3. **Live trace.** The pipeline's stages (`plan, triage, analysis, dq, narrate, check`, from the existing `on_stage` hook) stream to the browser as they start, each with its elapsed time. When the answer lands, the trace collapses to one line, "N steps · 14.8 s · $0.0245", built from `timings_ms` and `llm_usage`.
4. **Light and dark themes**, following the system by default, with a toggle. Use the mockup-B tokens (Geist, Geist Mono; the palette below). All text passes WCAG AA.

## Non-goals

- Authentication or SSO. The persona stays a selector, which is a documented limitation.
- Any change to the pipeline, guard, analysis, narration, evaluation or database.
- Cloud deployment. Local use and `docker compose` only.
- New chart designs. Charts are the existing Vega-Lite specs from `sherpa/charts.py`, restyled through a theme config.
- Multi-turn chat or conversation history. It stays one question, one answer, as today.

## Anti-goals (a failure even if it works)

- **The front end computes or formats a number.** Every displayed number is a string produced in Python: either a claim's `rendered` text or the API's `view` payload, which uses `format_value`. A second formatter in TypeScript would let the screen disagree with the bundle.
- **Data-derived text is ever rendered as HTML.** No `dangerouslySetInnerHTML`, and no URLs built from data. React text nodes only. This is the guarantee `tests/test_app.py::assert_inert` holds today.
- **A data-quality warning is hidden behind a click.**
- **The UI looks like a template.** In the UI chrome, hue appears only for data quality and confidence; everything else is grey. The "Unverified SQL" badge and warning count as confidence: that route caps confidence at medium. "Governed metric" and the claim-kind marks are grey. Charts follow the chart rule in Design → Charts.

## Constraints

- **Disk:** 4.1 GB free on `/` after today's cleanup (98% used). Use pnpm, whose content-addressed store hard-links packages instead of copying them, and keep dependencies few. Do not build Docker images; see Running it.
- **Toolchain:** Node 26.8, pnpm (installed), Python 3.12 with uv, and Postgres in `sherpa-db` on `127.0.0.1:5433`.
- **Versions** (checked on npm and PyPI on 2026-11-21): next 16.4.6, react 19.3.1, tailwindcss 4.3.5, shadcn CLI 4.23.0 (`-b radix`), lucide-react 1.77.0, react-resizable-panels 4.24.1, fastapi 0.165.0, uvicorn 0.54.0. Pin exact versions, and pick releases at least two weeks old where possible; vega-embed 7.4.0 was published yesterday, so use the release before it.
- **Network:** every server binds to `127.0.0.1`.
- **Tests:** the full Python suite stays green. `tests/test_app.py` (Streamlit AppTest) is replaced by API tests plus browser end-to-end tests that cover the same cases (see Testing).
- **Ownership:** `docs/CONTRACTS.md` §0 gives `app/` and `tests/fixtures/` to **ui**. This work stays inside `app/`, `web/`, `tests/test_api.py`, `tests/test_backend.py`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml` and the docs, and §0 is updated to match.

## Approaches considered

**How Next.js reaches the Python pipeline**

| Option | Trade-off | Verdict |
|---|---|---|
| **A FastAPI service in front of the pipeline**; Next.js proxies `/api/*` to it through `rewrites`. | Two processes. The `answer()` contract is reused unchanged, stages stream over SSE, and pydantic models give an OpenAPI schema, so TypeScript types are generated, not hand-written. | **Picked** |
| Next.js route handlers spawn `uv run python` per request. | About 2 to 3 s of cold start per question, and streaming stages needs hacks. | Rejected |
| Port the pipeline to TypeScript. | Throws away the tested core. | Rejected |

**Charts**

| Option | Trade-off | Verdict |
|---|---|---|
| **Render the existing Vega-Lite specs with vega-embed** | One source of truth. The specs are already tested in `tests/test_charts.py`, and the theme comes from CSS tokens. It is a heavier bundle, loaded lazily on the client only. | **Picked** (my call) |
| Recharts, as the design research suggested | Four chart builders (waterfall, bars, trend, recon bridge) duplicated in TypeScript and the tests lost. | Rejected |

**Package manager:** pnpm, because of the disk constraint (my call). **Streamlit:** deleted once the new UI passes its
parity tests. It is a single commit, so git can revert it (my call).

## Design

### Repository layout

```
app/backend.py     kept: fixture mode, demo questions, patched()
app/api.py         new: FastAPI app
app/view.py        new: AnswerBundle -> display-ready view (port of render.py's table and chart logic)
app/streamlit_app.py, app/render.py, .streamlit/, tests/test_app.py   deleted at the end
web/               new: Next.js app (App Router, TypeScript, Tailwind v4, shadcn/ui)
tests/test_api.py  new
tests/test_backend.py  new: the backend unit tests moved out of test_app.py
```

### API (`app/api.py`, uvicorn on `127.0.0.1:8000`)

| Route | Request | Response |
|---|---|---|
| `GET /api/health` | | `{ok, fixture_mode, fixture_reason}` |
| `GET /api/meta` | | Personas (key, label, regions). Demo questions with an optional persona override, and verified questions. Catalog for Explore: metrics (name, label, table, format), dimensions (name, label, tables, values), intents, window presets. Configured LLM backend. |
| `POST /api/ask` | `{question (1–500 chars), persona (must exist), plan?: AnalysisPlan, patch?: object}`. When `patch` is present, the server applies `backend.patched(plan, patch)`. | `text/event-stream`: one `event: stage` per stage, `{name, t_ms, elapsed}` (`elapsed` is `fmt_ms(t_ms)`, shown as-is by the trace), then `event: result` with `{bundle: AnswerBundle, view: View}`. The pipeline runs in a worker thread; `on_stage` pushes onto a queue the stream drains. In fixture mode, only `result` is sent. |
| `POST /api/explore/plan` | `{intent, metric, dimensions, window, baseline?, grain, filters[{dimension, values}]}` | `{question, plan}`, built exactly as `explore_page()` builds them today. Invalid input gets a 422. |
| `GET /api/eval` | | `{data, fixture: bool}`, or `{missing: true, path}`, or `{error}`. Same fallbacks as `eval_page()`. |
| `GET /api/runs` | | `{stats, recent}` (latest 50), or `{unavailable: reason}`. |

`AnswerBundle.answer()` never raises. Any unexpected exception still comes back as an error bundle with a run id,
as `backend.answer()` does today.

**View payload** (`app/view.py`). This is the rule; the builder chooses the field names. Every number the UI shows
is a pre-formatted string:
- **Key chart:** Vega-Lite specs keyed by dimension, the default dimension, Simpson text per dimension, and driver notes.
- **Reconciliation:** the bridge spec, plus components as `{name, amount, note}` strings and the source of truth.
- **Tables:** per evidence, `{columns, rows}` of strings, and driver effect tables as strings. This is the logic of `render.table_df`, `_effects_df` and `value_text`.
- **Evidence meta:** window, baseline, filters, tables, row count, hashes and SQL statements, passed through unchanged.

### Front end (`web/`)

- **Routes:**
  - `/` is Ask.
  - `/explore`, `/eval` and `/runs`.
  - Persona and theme live in client state persisted to `localStorage`; it is wrapped in try/catch and works without storage.
- **Shell:**
  - shadcn `Sidebar` with `collapsible="icon"`, holding the brand, persona select, nav and a footer of data version, as-of date and LLM backend.
  - The centre and the rail are `ResizablePanelGroup`s at 1280 px and wider, and a `Sheet` below that.
- **Ask page states:**
  - empty: question bar, demo chips, verified chips;
  - running: streaming trace;
  - answered;
  - clarification;
  - refusal;
  - error.
  A new question replaces the current answer.
- **Rail:**
  - **Plan:** the plan as a readable property list, with a raw-JSON toggle.
  - **Evidence:** one entry per evidence. Selecting one expands it to show window and baseline, filters as pills, tables, row count, query hashes with copy, the SQL statements with copy, its table and its chart, and "Cited by: claim n".
  - **Footprints:** run id, persona, data version, as-of date, time per stage, LLM backend and cost, cache hits, and Download run bundle.
- **Linked selection:** one `selectedEvidenceId` in context.
  - A chip click selects it and scrolls the rail.
  - Claims that cite the selected evidence are highlighted.
  - Chips are the only interactive badges; confidence and route badges are labels.
- **Charts:**
  - `<VegaChart spec>` is a client component that loads `vega-embed` with `next/dynamic` (`ssr: false`).
  - It applies a Vega config (axis, label and grid colours, font) from the CSS tokens and re-renders when the theme changes.
  - **Colours.** `sherpa/charts.py` hard-codes Okabe-Ito colours in every `scale.range`, which a Vega config cannot override. `VegaChart` therefore copies the spec and replaces those colours through one fixed map, separate for light and dark, covering every colour `charts.py` defines:
    - `DOWN #D55E00` becomes `--negative`;
    - `UP #009E73` becomes `--positive`;
    - `MIX #0072B2` becomes `--accent`;
    - `RATE #E69F00` becomes a second, muted accent;
    - `TOTAL #595959`, `#000000` and `#BBBBBB` become grey steps;
    - the remaining categorical colours (`#CC79A7`, `#56B4E9`, `#F0E442`) become a categorical palette that passes contrast in both themes.
  - The map lives in one file, and a unit test fails if `charts.py` emits a colour the map does not cover.
  - The pipeline and the downloaded bundle are unchanged; their chart colours are data, not what anyone views.
  - **Which chart.** The key chart is the real per-segment mix/rate waterfall from `charts.waterfall`, which shows *which* method moved, not the simplified 4-bar baseline → mix → rate → current drawing in mockup B. It is restyled with the colours above (my call; see below).
  - The rail is narrower than the centre, so a chart shown in the rail is sized to the rail's width.
- **Explore, Eval and Runs:**
  - **Explore:** the form sits in the centre and the rail shows the live plan preview from `/api/explore/plan`. Run streams into the same answer view.
  - **Eval:** tiles and a cases table; selecting a case shows its details in the rail.
  - **Runs:** stats tiles and a table; selecting a row shows that run's footprint in the rail.
- **Tokens:** set in `globals.css` (Tailwind v4 `@theme`), with light values on `:root` and dark values under `.dark`. Fonts are Geist and Geist Mono through `next/font/google`, with `tabular-nums` on all figures.
  - Light: bg `#F6F6F7`, surface `#FFFFFF`, text `#111214`, muted `#5A5E66`, border `#E1E2E5`, accent `#2456C4`, positive `#167A3C`, negative `#C22F2A`, warning `#8C5800`.
  - Dark: bg `#0A0B0D`, surface `#131417`, text `#EDEEF0`, muted `#9A9EA7`, border `#25272C`, accent `#7FA8FF`, positive `#5ED18E`, negative `#FF7B74`, warning `#F0BF4F`.
  - Input outlines use a darker border step that reaches at least 3:1.
- **Types:** `pnpm types` generates `web/lib/api-types.ts` from FastAPI's `/openapi.json` with openapi-typescript. The generated file is committed.

### Running it

- **Local:**
  - `make api` runs uvicorn.
  - `make web` runs `pnpm dev`.
  - `make app` starts both, killing the API on exit.
  - Next.js rewrites `/api/*` to `SHERPA_API_URL`, default `http://127.0.0.1:8000`.
- **Docker:**
  - `api` service: the existing Python image, with CMD set to uvicorn on `0.0.0.0:8000`, reachable inside the compose network only.
  - `web` service: a Next.js `output: "standalone"` image, published on `127.0.0.1:3000`.
  - The 8501 mapping is removed.
  - The repo's `CLAUDE.md` says "no new docker images" while the disk is nearly full (98% after today's cleanup). So the Docker files are written and checked with `docker compose config`, but **not built here**. The README says so.
- **Formatting outside the bundle:**
  - Eval and Runs tiles, and trace timings, are formatted in Python too. Streamlit's `_fmt` helper (pct, int, ms, usd) moves into the API.
  - A past run's footprint shows only what `app.runs` stores. That excludes the as-of date and the full bundle, so those two items are hidden for past runs.
- **Dependencies:**
  - Python: `fastapi` and `uvicorn` added for runtime; `httpx` added for development, for TestClient. `streamlit` is removed. `altair` moves to dev dependencies, because only `tests/test_charts.py` uses it.
  - Node: next, react, react-dom, tailwindcss, @tailwindcss/postcss, radix-ui (through shadcn), lucide-react, react-resizable-panels, vega-embed with vega and vega-lite. For development: typescript, @types/react, @types/node, @playwright/test, openapi-typescript.

## Testing

- **pytest `tests/test_api.py`** (fixture mode, TestClient):
  - the `meta` shape;
  - `/ask` streams `stage` events then `result`;
  - an unknown persona gets 422, and a question over 500 characters is rejected;
  - `patch` is applied;
  - Explore builds the same plan as today's `explore_page()` for a fixed input;
  - the eval and runs fallbacks;
  - every number in `view` is a string.
- **pytest `tests/test_backend.py`:** fixture matching, `patched`, `seed_of` and demo questions, moved unchanged from `test_app.py`.
- **Playwright `web/e2e/`** (fixture mode, system Chrome): one test per `test_app.py` UI case, plus the new layout.
  - explain_change: shows tags, SQL, chart and data-quality banners above the headline.
  - SQL route: labelled "Unverified SQL", and injected markup stays inert text.
  - Clarification: choosing an option answers.
  - Refusal: the suggestion runs.
  - Reconcile: the bridge renders.
  - Partial bundle: renders without crashing.
  - Error card: keeps the run id.
  - Demo chip: switches the persona.
  - Every route: renders.
  - Explore: builds and runs.
  - Chip selection: opens the rail entry and highlights claims.
  - Theme toggle: works.
  - Below 1280 px: the rail becomes a sheet.
- **Build checks:** `pnpm build`, `tsc --noEmit` and lint, all clean.
- **Live smoke:** one real question through the UI with the claude-cli backend, with a screenshot.

## Rollout

All work is on `feature/nextjs-ui`, in small conventional commits. **`main` is untouched, with Streamlit still on it,
until the whole UI passes.** No half-finished UI ever reaches the branch that reviewers open. The work runs in three
phases, each ending in a state that could be demoed from the branch:

1. **API and shell:** the API (`/meta`, `/ask` with SSE, `/health`), the layout shell, Ask with the trace, the answer, the rail and linked selection, and charts.
2. **Remaining screens:** clarification, refusal and error states, Explore, Eval and Runs, the theme toggle, and narrow screens.
3. **Parity and cleanup:**
   - Playwright parity, then Docker files.
   - Delete Streamlit, then update README, `docs/DEMO.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md` §0 and the UI part of `docs/TASKS.md`.
   - Merge to `main` with `--no-ff`, then push.

In the tests, fixture mode sends no stage events. The API's stream tests use a fake pipeline that calls `on_stage`,
and timings are never invented. There is also an end-to-end test for the deep link.

## Left to the builder

- Component breakdown and file names under `web/`.
- Field names in the `view` payload, keeping the rule that numbers are strings from Python.
- Interface copy, empty states, and mobile polish beyond the top bar, stacked panes and sheet.

## Calls made for Harsh to check

- FastAPI and uvicorn as new runtime dependencies.
- Reusing the Vega-Lite specs with vega-embed instead of Recharts.
- pnpm, because of the disk constraint.
- Streamlit deleted after parity, not kept alongside.
- Number formatting only in Python.
- The real per-segment waterfall instead of the simplified 4-bar chart in the mockup, with colours remapped on the client.
- Docker files written but not built, following the repo's "no new docker images" rule.

## Open questions

1. **Deadline.** When is the submission due, and must this UI be the one submitted? The answer sets how far phase 3
   can go before submission. If the deadline is close, `main` keeps Streamlit and this work lands after it.
