# Next.js Inspector Rail UI: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit UI with a Next.js "Inspector Rail" front end, served by a FastAPI layer over the existing pipeline, with full feature parity.

**Architecture:**
- **API:** FastAPI (`app/api.py`) wraps `app/backend.py` and `sherpa.pipeline.answer`. It streams stage events over SSE. It also turns every `AnswerBundle` into a display-ready `View` (`app/view.py`) in which every number is already a string.
- **Front end:** a Next.js 16 App Router app in `web/`. It renders the bundle and view without computing anything, proxies `/api/*` to FastAPI, and draws the existing Vega-Lite specs with vega-embed.

**Tech stack:**
- Python: FastAPI 0.165.0 and uvicorn 0.54.0, with httpx for tests.
- Next.js 16.4.6, React 19.3.1, Tailwind CSS 4.3.5, and shadcn/ui (CLI 4.23.0, `-b radix`).
- lucide-react 1.77.0, react-resizable-panels 4.24.1, and vega-embed (the release before 7.4.0).
- @playwright/test, using the system Chrome through `channel: "chrome"`.
- pnpm.

**Spec:** `docs/superpowers/specs/2026-11-21-nextjs-inspector-ui-design.md`. Read it before any task.

## Global Constraints

- Every server binds `127.0.0.1`. Ports: API 8000 (dev) or 8765 (e2e); web 3000 (dev) or 3765 (e2e).
- **The front end never computes or formats a number.** Every displayed number is a string from Python: a claim's `rendered`, a `View` field, or an `/api/eval` or `/api/runs` field.
- No `dangerouslySetInnerHTML`, no `eval`, and no `href` or `src` built from data. Data-derived text is rendered only as React text nodes.
- Data-quality banners always render above the headline and are never collapsed.
- **Chrome hue rule:** hue appears only for data quality and confidence; the rest is grey. Charts are recoloured through `web/lib/chart-colors.json`.
- **Tokens:** light bg `#F6F6F7`, surface `#FFFFFF`, text `#111214`, muted `#5A5E66`, border `#E1E2E5`, accent `#2456C4`, positive `#167A3C`, negative `#C22F2A`, warning `#8C5800`. Dark bg `#0A0B0D`, surface `#131417`, text `#EDEEF0`, muted `#9A9EA7`, border `#25272C`, accent `#7FA8FF`, positive `#5ED18E`, negative `#FF7B74`, warning `#F0BF4F`. Input outlines use a border step of at least 3:1 (light `#8C8F95`, dark `#5E626A`). Fonts: Geist and Geist Mono through `next/font/google`, with `tabular-nums` on figures.
- **Dependencies:** pnpm only; pin exact versions; no dependency beyond those named in the spec and this plan.
- Do not build Docker images (repo `CLAUDE.md`). Never run `docker compose down -v` or prune volumes.
- All work on `feature/nextjs-ui`; `main` is not touched until the final merge.
- **Commits:** small, conventional, staging explicit paths only. No AI attribution lines (no Co-Authored-By or "Generated with" trailers).
- **Stay green:** `uv run pytest` must pass after every Python task. After every web task, `pnpm -C web build`, `pnpm -C web exec tsc --noEmit` and the e2e suite must pass.

## Review Focus

1. **SSE buffered by the Next.js proxy:** the stages arrive all at once with the result. Expected: each stage appears as it happens.
   - Task 3 sets `compress: false` and the no-transform headers.
   - Task 8's live smoke checks that the first stage arrives more than 1 s before the result.
2. **API unreachable, or the stream breaks mid-run:** expected an error card naming the problem, not a spinner that never ends. Pinned by the e2e test in Task 4 (`api failure shows an error card`).
3. **A new question while one is running:** expected the latest question to win, the earlier stream to be aborted, and no stale result to overwrite it. Pinned in Task 4 (`second question wins`).
4. **Long data-derived strings** (300-character SQL lines, a 200-row table, long merchant names): expected no horizontal page scroll. Pinned in Task 5 (`no page overflow on sql_route`).
5. **`localStorage` unavailable** (private mode or blocked storage): expected the app to load and answer, with persona and theme simply not remembered. Pinned in Task 3 (`works without localStorage`).

---

## File map

| Path | Responsibility |
|---|---|
| `app/view.py` | `build_view(bundle) -> View`: claims, evidence, key charts, drivers, recon and footprint as display strings. Port of `app/render.py` logic. |
| `app/explore.py` | `build_explore_plan(form) -> tuple[str, AnalysisPlan]`: port of `explore_page()` plan building. |
| `app/api.py` | FastAPI app: `/api/health`, `/api/meta`, `/api/ask` (SSE), `/api/explore/plan`, `/api/eval`, `/api/runs`. |
| `app/backend.py` | Kept. `answer()` gains `on_stage`. |
| `tests/test_view.py`, `tests/test_api.py`, `tests/test_backend.py` | Python tests. `test_backend.py` takes the pure-helper tests from `test_app.py`. |
| `tests/fixtures/partial.json` | Partial bundle (dangling and duplicate evidence ids, an unformatted string value, `cost_usd: None`), written by `make_bundles.py`. |
| `tests/test_chart_colors.py` | Every hex colour in `sherpa/charts.py` is a key of both themes in `web/lib/chart-colors.json`. |
| `web/` | Next.js app; files named in tasks 3 to 7. |
| `web/e2e/*.spec.ts`, `web/playwright.config.ts` | Browser tests in fixture mode. |
| `Makefile`, `Dockerfile`, `web/Dockerfile`, `docker-compose.yml` | Run targets and container files (written, not built). |

---

### Task 1: View model (`app/view.py`)

**Files:**
- Create: `app/view.py`
- Create: `tests/test_view.py`
- Modify: none

**Interfaces:**
- Consumes:
  - `sherpa.contracts.{AnswerBundle, Evidence, format_value}`
  - `sherpa.charts.{waterfall, recon_bridge}`
  - `sherpa.config.{load_catalog, load_access}`
- Produces (pydantic models, all fields required unless defaulted):

```python
class KV(BaseModel): label: str; value: str
class Table(BaseModel): columns: list[str]; rows: list[list[str]]          # every cell a display string ("" for None)
class ClaimView(BaseModel):
    n: int                                   # 1-based position in bundle.claims
    kind: Literal["fact", "hypothesis", "recommendation", "caveat"]
    text: str                                # CheckedClaim.rendered
    ok: bool; problems: list[str]
    evidence_ids: list[str]                  # cited ids present in bundle.evidence, de-duplicated, in order
    missing_ids: list[str]                   # cited ids absent from bundle.evidence
class EvidenceView(BaseModel):
    id: str; title: str; kind: str
    meta: list[KV]                           # Window, Baseline, Filters ("none" if empty), Tables, Rows; skip None
    sql: list[KV]                            # label "SQL 1 of 3 · sha256 <hash or n/a>", value = statement
    values: list[KV]                         # label "{E1.r0}", value = formatted (render.value_text rules)
    table: Table | None                      # render.table_df rules; None when evidence.table is empty
    chart: dict | None                       # evidence.chart unchanged
    cited_by: list[int]                      # ClaimView.n values that cite this id
class KeyChart(BaseModel):
    dimension: str; label: str               # label = catalog dimension label, else dimension with "_" -> " "
    spec: dict                               # charts.waterfall(dec)
    simpson: str | None                      # render.simpson_callout text when dec.simpson_flag, else None
    summary: str                             # "By payment method: mix -0.92 pp, rate +0.08 pp."
class DriverSection(BaseModel):
    heading: str                             # render.driver_tables heading text
    tables: list[tuple[str, Table]]          # (caption "payment method · explanatory score 0.93 · Simpson flag", effects table)
    drilldown: Table | None
    notes: list[str]
class ReconView(BaseModel): spec: dict; components: Table; source_of_truth: str
class Footprint(BaseModel):
    items: list[KV]                          # Run, Persona (label), Data, As of, Total, LLM ("claude-cli · $0.0245"), Cache ("20 of 20 queries")
    stages: list[KV]                         # timings_ms for plan, triage, analysis, dq, narrate, check (present keys only)
    summary: str                             # "6 steps · 14.8 s · $0.0245" (omit parts that are missing)
class View(BaseModel):
    claims: list[ClaimView]; evidence: list[EvidenceView]
    key_charts: list[KeyChart]; default_dimension: str | None   # drivers.top_dimension if present in key_charts
    fallback_chart: KV | None                # when no drivers and no recon: first evidence with a chart -> KV(label="E2 · <title>", value="E2"); the UI draws that EvidenceView's chart
    drivers: DriverSection | None; recon: ReconView | None
    footprint: Footprint
    as_of: str | None                        # "19 Nov 2026"
def build_view(b: AnswerBundle) -> View
def fmt_ms(ms: int | float | None) -> str    # None -> "n/a"; <100 -> "20 ms"; else "6.1 s"
```

- [ ] **Step 1: Write failing tests in `tests/test_view.py`** (fixture bundles via `app.backend.load_fixture`):
  - `test_claims_carry_rendered_text_and_dedup_ids`:
    - the explain_change view claims' `text` equal `[c.rendered for c in bundle.claims]`;
    - for a claim with `evidence_ids=["E1","E1","E9"]`, `evidence_ids == ["E1"]` and `missing_ids == ["E9"]`.
  - `test_tables_match_streamlit_formatting`: the same assertions as `test_app.py::test_result_tables_render_like_claims`, against `View.evidence[i].table`:
    - the `rate` column is `["92.8%", "91.7%"]`;
    - `share0` is `["40.0%", "60.0%"]`;
    - `mix_effect` is `["-0.80 pp", "-0.80 pp"]`;
    - recon `amount_inr[0]` is `"₹4.20 L"`;
    - sql_route `display_name[1]` is the injection string verbatim, `merchant_id[0] == "M0042"` and `failed[0] == "812"`.
  - `test_every_number_is_a_string`:
    - walk `build_view(b).model_dump()` for each fixture except the `spec` and `chart` dicts;
    - assert no `int` or `float` leaf except `ClaimView.n` and `EvidenceView.cited_by` entries.
  - `test_key_charts_and_simpson`:
    - explain_change has `len(key_charts) == len(bundle.drivers.dimensions)` and `default_dimension == bundle.drivers.top_dimension`;
    - the flagged dimension's `simpson` contains `"Simpson's paradox"`.
  - `test_recon_view`: the reconcile fixture has a `recon.components.columns == ["component", "amount", "note"]` and a non-empty spec.
  - `test_footprint`:
    - with `timings_ms={"plan":6127,"narrate":8182,"total":14827,"queries":20,"cache_hits":20}` and `llm_usage={"backend":"claude-cli","cost_usd":0.02451}`, `summary == "2 steps · 14.8 s · $0.0245"`;
    - the `Cache` item is `"20 of 20 queries"`;
    - with `cost_usd=None` there is no `$` in the summary and nothing raises.
  - `test_fmt_ms`: `fmt_ms(None) == "n/a"`, `fmt_ms(20) == "20 ms"`, `fmt_ms(6127) == "6.1 s"`.
- [ ] **Step 2: Run the tests and see them fail.** `uv run pytest tests/test_view.py -q` should report import errors.
- [ ] **Step 3: Implement `app/view.py`.** Port `render.table_df`, `value_text`, `_effects_df` (columns `segment, share before, share now, rate before, rate now, mix (pp), rate (pp), total (pp), z, q (BH), supported, significant, material`; percentages `"%.1f%%"`, pp `"%+.2f pp"`, z `"%.2f"`, q `"%.2g"`, bools `"yes"`/`"no"`), `driver_tables`, `simpson_callout`, `evidence_meta` and `sql_blocks` into pure functions that return strings. Use `format_value` for every metric value. `render.py` stays until Task 8.
- [ ] **Step 4: Run the tests and see them pass.** `uv run pytest tests/test_view.py -q` should pass, and `uv run pytest -q` should still be green.
- [ ] **Step 5: Commit.** `git add app/view.py tests/test_view.py && git commit -m "feat(api): display-ready View built from AnswerBundle"`.

### Task 2: FastAPI service (`app/api.py`, `app/explore.py`)

**Files:**
- Create: `app/api.py`, `app/explore.py`, `tests/test_api.py`, `tests/test_backend.py`, `tests/fixtures/partial.json`
- Modify:
  - `app/backend.py`: `answer()` gains `on_stage: Callable[[str], None] | None = None`, passed to `pipe.answer(..., on_stage=on_stage)`.
  - `tests/fixtures/make_bundles.py`: also writes `partial.json`.
  - `pyproject.toml` and `uv.lock`: add `fastapi==0.165.0` and `uvicorn==0.54.0`; add `httpx` to dev.
  - `Makefile`: target `api`.

**Interfaces:**
- Consumes: Task 1's `build_view`, `View` and `fmt_ms`; `app.backend.*`; `sherpa.runs.{run_stats, recent_runs}`; `sherpa.db.data_version`.
- Produces (HTTP, JSON bodies; pydantic models in `app/api.py`, so they appear in OpenAPI):
  - `GET /api/health` returns `{ok: true, fixture_mode: bool, fixture_reason: str | None}`.
  - `GET /api/meta` returns:
    - `personas: [{key, label, regions}]` and `default_persona: "head"`;
    - `demo: [{question, persona: str | None}]`: `backend.demo_questions(seed)` plus `{"question": "Compare North vs South success rate", "persona": "rm_south"}`;
    - `verified: [str]`;
    - `catalog: {intents: [{value,label}], metrics: [{name,label,table}], dimensions: [{name,label,tables,values}], windows: [{value,label}], grains: ["day","hour"]}`;
    - `llm_backend: str`;
    - `data_version: str | None` and `as_of: str | None` (formatted). These come from `sherpa.db.data_version(default_persona)` inside try/except; the seed comes from `backend.seed_of`, else 42.
    - `fixture_mode: bool`.
  - `POST /api/ask` takes `AskRequest {question: str (1..500 after strip), persona: str (must be in access.personas, else 422), plan: AnalysisPlan | None, patch: dict | None, fixture: str | None}`.
    - `fixture` is honoured only in fixture mode, and must name an existing `tests/fixtures/*.json` bundle, else 422.
    - When `patch` is set, `plan = backend.patched(plan, patch)`; it is a 422 if `plan` is None.
    - Response: `text/event-stream` with headers `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`. Events:
      - `event: stage` with `data: {"name": str, "t_ms": int}`, where `t_ms` is milliseconds since the request started;
      - one final `event: result` with `data: {"bundle": AnswerBundle, "view": View}`.
    - The pipeline runs in a `threading.Thread`; `on_stage` puts onto a `queue.Queue` that the generator drains. An unexpected exception becomes an error bundle with a run id, as `backend.answer` does.
  - `POST /api/explore/plan` takes `ExploreForm {intent, metric, dimensions: list[str] = [], window: str = "last_7_days", baseline: str | None, grain: Literal["day","hour"] = "day", filters: list[Filter] = []}` and returns `{question: str, plan: AnalysisPlan}`. Unknown metric, dimension, intent or preset gets a 422.
  - `GET /api/eval` returns one of:
    - `{status: "ok", fixture: bool, generated_at, data_version, tiles: [{label, sherpa, baseline}], cases: [{id, kind, question, sherpa_pass: bool, sherpa_detail, baseline_pass: bool, baseline_detail}]}`;
    - `{status: "missing", path}`;
    - `{status: "error", message}`.
    The 7 tiles follow `EVAL_METRICS` from `streamlit_app.py`, formatted by the ported `_fmt`.
  - `GET /api/runs` returns `{status: "ok", tiles: [KV], recent: [{run_id, asked_at, persona, question, status, route, confidence, total, cost, footprint: [KV]}]}` (all strings) or `{status: "unavailable", message}`. There are 7 tiles, as in `runs_page`.
  - `app/explore.py` provides `build_explore_plan(form: ExploreForm) -> tuple[str, AnalysisPlan]`. The question text follows `explore_page()`'s `parts` rule exactly.

- [ ] **Step 1: Move the pure-helper tests.**
  - Create `tests/test_backend.py` with `test_fixture_matching`, `test_a_plan_handed_back_is_never_re_asked_or_refused`, `test_patched_resolves_the_plan`, `test_seed_of` and `test_demo_questions_from_ground_truth`, copied verbatim from `tests/test_app.py`.
  - Leave `test_app.py` in place until Task 8.
- [ ] **Step 2: Write failing tests in `tests/test_api.py`.** Use `fastapi.testclient.TestClient(app)`, with `SHERPA_UI_FIXTURES=1` via monkeypatch unless stated.
  - `test_health_reports_fixture_mode`.
  - `test_meta_shape`:
    - 2 personas;
    - the last demo item is `{"question": "Compare North vs South success rate", "persona": "rm_south"}`;
    - `verified` is non-empty;
    - `catalog.metrics` contains `success_rate`.
  - `test_ask_streams_result_in_fixture_mode`: the events are exactly one `result`, whose `bundle.status == "answered"` and whose `view.claims` is non-empty.
  - `test_ask_streams_stages_from_pipeline`:
    - monkeypatch `backend.pipeline_status` to return a fake module whose `answer(q, p, plan=None, on_stage=None)` calls `on_stage` for `plan, triage, analysis, dq, narrate, check`, then returns `load_fixture("explain_change")`;
    - assert the event names are 6 `stage` then 1 `result`, and the `t_ms` values never decrease.
  - `test_ask_rejects_bad_input`:
    - unknown persona gets 422;
    - `"x"*501` gets 422;
    - whitespace-only gets 422;
    - `fixture="../../etc/passwd"` gets 422;
    - `patch` without `plan` gets 422.
  - `test_ask_fixture_param_only_in_fixture_mode`: with `SHERPA_UI_FIXTURES` unset and a fake pipeline, `fixture="error"` is ignored, so the fake's bundle is returned.
  - `test_ask_patch_applies`: post the clarify fixture's plan with its first option's `plan_patch`; the result status is not `clarify`.
  - `test_explore_plan_matches_streamlit`:
    - the form `{intent:"breakdown", metric:"success_rate", dimensions:["payment_method"], window:"last_7_days", filters:[{dimension:"region", values:["South"]}]}` gives the question `"Breakdown: Success rate by Payment method last 7 days where Region in South"` and `plan.route == "catalog"`;
    - an unknown metric gets 422.
  - `test_eval_and_runs_fallbacks`:
    - `/api/eval` gives `status == "ok"` with 7 tiles (the fixture or `eval/results/latest.json`);
    - `/api/runs` with `sherpa.runs.run_stats` monkeypatched to raise gives `status == "unavailable"`.
  - `test_partial_fixture_view`:
    - `/api/ask` with `fixture="partial"` returns `view.claims[0].missing_ids == ["E9"]`;
    - nothing in `view` is a float.
- [ ] **Step 3: Run the tests and see them fail.** `uv run pytest tests/test_api.py tests/test_backend.py -q` should report import errors for `app.api`.
- [ ] **Step 4: Write `partial.json`.** Extend `make_bundles.py` to write it: the explain_change bundle with these mutations, copied from `test_partial_pipeline_data_does_not_crash_the_card`:
  - `evidence[0].values["note"] = "free text, no format"`;
  - `claims[0].evidence_ids = ["E1","E1","E9"]`;
  - `llm_usage = {"backend": "template", "cost_usd": None}`;
  - `run_id = "fx-partial-0001"`.

  Run `uv run python tests/fixtures/make_bundles.py`, then check `git diff --stat tests/fixtures`: only `partial.json` should be new, and the other fixtures unchanged.
- [ ] **Step 5: Implement `app/explore.py`, the `on_stage` pass-through in `app/backend.py`, and `app/api.py`.** Then add the deps with `uv add fastapi==0.165.0 uvicorn==0.54.0` and `uv add --dev httpx`, and the Makefile target `api: uv run uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload`.
- [ ] **Step 6: Run the tests and see them pass.** `uv run pytest -q` should be all green.
- [ ] **Step 7: Smoke-test the real pipeline.**
  - Run `uv run uvicorn app.api:app --port 8000 &`.
  - Run `curl -N -s -X POST localhost:8000/api/ask -H 'content-type: application/json' -d '{"question":"Why did success rate drop last week?","persona":"head"}' | grep -c '^event: stage'`. It should print `6`, followed by one `event: result`.
  - Kill the server.
- [ ] **Step 8: Commit.** Stage `app/api.py app/explore.py app/backend.py tests/test_api.py tests/test_backend.py tests/fixtures/make_bundles.py tests/fixtures/partial.json pyproject.toml uv.lock Makefile`, with the message `feat(api): FastAPI service with SSE stages, explore, eval and runs`.

### Task 3: Web scaffold, theme, shell and e2e harness

**Files:**
- Create in `web/`:
  - config: `package.json`, `pnpm-lock.yaml`, `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `components.json`;
  - app: `app/layout.tsx`, `app/globals.css`, `app/page.tsx` (placeholder Ask header only), `app/explore/page.tsx`, `app/eval/page.tsx`, `app/runs/page.tsx` (placeholder headers);
  - shell: `components/shell/app-sidebar.tsx`, `components/shell/workspace.tsx`, `components/shell/theme-toggle.tsx`;
  - lib: `lib/theme.ts`, `lib/api.ts`, `lib/api-types.ts` (generated), `lib/store.tsx`;
  - `components/ui/*` (shadcn);
  - e2e: `playwright.config.ts`, `e2e/shell.spec.ts`.
- Modify:
  - `Makefile`: targets `web`, `app` (api + web; kills the API on exit), `types`, `e2e`.
  - `.gitignore`: `web/node_modules`, `web/.next`, `web/test-results`, `web/playwright-report`.

**Interfaces:**
- Consumes: Task 2's HTTP API (types generated from `http://127.0.0.1:8000/openapi.json`).
- Produces:
  - `lib/api.ts`:
    - `getMeta(): Promise<Meta>`, `explorePlan(form): Promise<{question, plan}>`, `getEval(): Promise<EvalResponse>`, `getRuns(): Promise<RunsResponse>`.
    - `ask(req: AskRequest, on: {stage(e: {name: string; t_ms: number}): void; result(r: {bundle: AnswerBundle; view: View}): void}, signal: AbortSignal): Promise<void>`. It POSTs with `fetch` and parses SSE from `response.body` (split on blank lines; `event:` and `data:` fields). It throws `Error("Sherpa API unreachable: …")` on a network failure or non-2xx, and `Error("The answer stream ended early")` when there is no `result`.
  - `lib/store.tsx`:
    - `SherpaProvider` and `useSherpa()`, which return `{meta, persona, setPersona, run, ask(question: string, opts?: {plan?, patch?, persona?, fixture?}), selectedEvidenceId, selectEvidence(id: string | null)}`.
    - `run` is `{status: "idle" | "running" | "done" | "failed", question?: string, stages: {name: string; t_ms: number}[], result?: {bundle, view}, error?: string}`.
    - Each `ask` aborts the previous controller and ignores callbacks from stale runs (a run counter).
    - The persona is persisted under `localStorage["sherpa.persona"]`, with every access in try/catch. An unknown stored persona falls back to `meta.default_persona`.
  - `components/shell/workspace.tsx`: `<Workspace center={ReactNode} rail={ReactNode} railTitle={string} railOpen?={boolean} onRailOpenChange?>`.
    - At 1280 px and wider: a `ResizablePanelGroup` (centre 64 / rail 36, min 28) with `data-testid="rail"`.
    - Below 1280 px: the rail in a shadcn `Sheet` (side right) with `data-testid="rail-sheet"`, opened by a button "Inspector" or by `railOpen`.
  - `components/shell/app-sidebar.tsx`: shadcn `Sidebar collapsible="icon"` with:
    - brand "Sherpa";
    - persona `Select` (`data-testid="persona"`);
    - nav Ask `/`, Explore `/explore`, Eval `/eval`, Runs `/runs` (lucide icons);
    - footer in Geist Mono: data version, as-of date and LLM backend from the latest run, else from meta;
    - the "Fixture mode" notice when `meta.fixture_mode`.
    On phones it uses the shadcn mobile sheet with a top bar holding `SidebarTrigger`.
  - `lib/theme.ts` and `theme-toggle.tsx`:
    - an inline script in `<head>` sets `class="dark"` from `localStorage["sherpa.theme"]` (`light`, `dark` or `system`), else from `prefers-color-scheme`, before paint, inside try/catch;
    - the toggle cycles light, dark and system (`data-testid="theme-toggle"`).
  - `next.config.ts`: `output: "standalone"`, `compress: false`, and `rewrites` `/api/:path*` to `${process.env.SHERPA_API_URL ?? "http://127.0.0.1:8000"}/api/:path*`.
  - `package.json` scripts: `dev` (`next dev -H 127.0.0.1 -p 3000`), `build`, `start` (`next start -H 127.0.0.1`), `types` (`openapi-typescript http://127.0.0.1:8000/openapi.json -o lib/api-types.ts`), `e2e` (`playwright test`).
  - `playwright.config.ts`:
    - `use: {channel: "chrome", baseURL: "http://127.0.0.1:3765"}`;
    - two `webServer`s:
      - `cd .. && SHERPA_UI_FIXTURES=1 uv run uvicorn app.api:app --host 127.0.0.1 --port 8765`, waiting on `http://127.0.0.1:8765/api/health`;
      - `SHERPA_API_URL=http://127.0.0.1:8765 pnpm build && SHERPA_API_URL=http://127.0.0.1:8765 pnpm start -p 3765`, waiting on `http://127.0.0.1:3765`;
    - `reuseExistingServer: !process.env.CI`.

- [ ] **Step 1: Scaffold.**
  - `pnpm create next-app@16.4.6 web --ts --app --tailwind --eslint --no-src-dir --import-alias "@/*" --use-pnpm`.
  - Pin `next`, `react` and `react-dom` exactly.
  - Run `pnpm -C web dlx shadcn@4.23.0 init -b radix`, then add `sidebar resizable sheet button badge select tabs collapsible tooltip table separator input toggle-group scroll-area skeleton`.
  - Add `lucide-react@1.77.0` and `react-resizable-panels@4.24.1` if shadcn did not pin them, and dev `@playwright/test openapi-typescript`.
- [ ] **Step 2: Write the failing e2e `web/e2e/shell.spec.ts`:**
  - `every route renders the shell`: `/`, `/explore`, `/eval` and `/runs` each show the sidebar brand "Sherpa" and their heading.
  - `persona select lists both personas`.
  - `theme toggle switches the html class`: from `dark` absent to `dark` present.
  - `works without localStorage`: `addInitScript` replaces `window.localStorage` with an object whose methods throw; `/` still renders the brand and persona select.
  - `rail becomes a sheet below 1280px`: at viewport 1100×900, `rail-sheet` opens from the "Inspector" button; at 1400×900, `rail` is visible.
- [ ] **Step 3: Run it and see it fail.** `pnpm -C web e2e` should fail on missing elements.
- [ ] **Step 4: Implement the shell.**
  - `globals.css`: the tokens from Global Constraints in Tailwind v4 `@theme inline`, mapped to shadcn variables (`--background`, `--card`, `--foreground`, `--muted-foreground`, `--border`, `--input`, `--primary`, `--ring`, plus `--positive`, `--negative`, `--warning` and `--sidebar-*`).
  - Then `layout.tsx` (Geist fonts and the no-flash script), the theme helpers, the sidebar, the workspace, `store.tsx` with `getMeta` on mount, and the API client.
  - Generate `lib/api-types.ts` by running `make api` in the background, then `pnpm -C web types`.
- [ ] **Step 5: Run the checks and see them pass.**
  - `pnpm -C web exec tsc --noEmit` should pass.
  - `pnpm -C web build` should pass.
  - `pnpm -C web e2e` should report 5 passed.
- [ ] **Step 6: Commit.** Stage `web` (excluding ignored files), `Makefile` and `.gitignore`, with the message `feat(web): Next.js shell with Inspector Rail layout, theme, API client, e2e harness`.

### Task 4: Ask page, live trace and answer view

**Files:**
- Create: `web/components/ask/question-bar.tsx`, `web/components/ask/chips.tsx`, `web/components/answer/trace.tsx`, `web/components/answer/answer-view.tsx`, `web/components/answer/claims.tsx`, `web/e2e/ask.spec.ts`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes:
  - Task 3: `useSherpa()`, `Workspace`, and the API types.
  - Task 1: `View.claims`, `View.footprint` and `View.as_of`.
- Produces:
  - `<AnswerView bundle view />`, for answered bundles (Task 6 adds the other statuses).
  - `<EvidenceChip id missing? />` (`data-testid="chip-E2"`). Clicking calls `selectEvidence(id)`, sets `aria-pressed`, and requests the rail to open on narrow screens. A missing chip renders as disabled text "E9 · not in this bundle".
  - `data-testid` hooks:
    - `question`, `ask-button`, `demo-chip`, `verified-chip`, `trace`;
    - `dq-banner`, `headline`, `badge-confidence`, `badge-route`, `footprint-line`, `claim` (with `data-kind` and `data-cites="E1 E2"`);
    - `download-bundle`, `error-card`.
  - The trace sets `data-stage-times` (JSON of client-side arrival times in ms) for Task 8's live check.

- [ ] **Step 1: Write the failing `web/e2e/ask.spec.ts`:**
  - `explain_change shows tags, DQ before headline, footprint`:
    - ask "Why did success rate drop last week?";
    - claims include kinds fact, hypothesis, recommendation and caveat;
    - every `dq-banner`'s bounding box `y` is less than the `headline`'s `y`;
    - the footprint line contains `run`;
    - the sidebar footer shows "v1 · seed 42" and "19 Nov 2026";
    - `download-bundle` is visible.
  - `sql_route is labelled and injection stays text`:
    - ask "Which merchants had the most failed payments last week?";
    - `badge-route` has the text "Unverified SQL", and the warning text contains "Unverified SQL";
    - the page contains no `img` element whose `src` comes from the fixture;
    - the injection string (read from `tests/fixtures/sql_route.json` `evidence[0].table[1].display_name` with `fs`) appears in the DOM as text after clicking chip `E1`. The table assertion itself belongs to Task 5, so here just assert `page.content()` does not contain the raw `<img` sequence from the injection.
  - `demo chip switches persona`: clicking the demo chip "Compare North vs South success rate" sets the `persona` select to "Regional manager, South" and shows text containing "out of scope".
  - `deep link asks once and ignores unknown persona`: `/?q=Why%20did%20success%20rate%20drop%20last%20week%3F&persona=superuser` shows the headline, with the persona showing "Business head (all regions)".
  - `empty question is ignored`: clicking `ask-button` with an empty box makes no `/api/ask` request (`page.on("request")`).
  - `api failure shows an error card`: `page.route("**/api/ask", r => r.abort())`, then ask; the `error-card` contains "Sherpa API unreachable".
  - `second question wins`:
    - route the first `/api/ask` with a 1500 ms delay before `continue()`, and the second without a delay;
    - ask the sql_route question, then immediately the explain_change question;
    - after 3 s the `headline` is the explain_change headline, and `badge-route` is not "Unverified SQL".
- [ ] **Step 2: Run it and see it fail.** `pnpm -C web e2e e2e/ask.spec.ts` should fail.
- [ ] **Step 3: Implement the Ask page.**
  - The `?q=`, `persona=` and `fixture=` deep link is read once with `useSearchParams` and is ignored when the persona is unknown.
  - Chips come from `meta.demo` (setting the persona when an item carries one) and from `meta.verified`.
  - The trace shows streamed stages, then collapses to `view.footprint.summary` when done.
  - The answer card comes from `bundle` and `view`:
    - DQ banners first, with the severity icon and text;
    - the headline;
    - confidence and route badges;
    - for the `sql` route, the warning copy from `render.answered`;
    - the footprint line from `view.footprint.items`;
    - a collapsible "Why {confidence} confidence" from `bundle.confidence_reasons`;
    - assumptions from `bundle.plan.assumptions`;
    - the claims list.
  - Download writes `JSON.stringify(bundle, null, 2)` to a Blob named `sherpa-run-<run_id sanitised to [A-Za-z0-9_.-]>.json`.
- [ ] **Step 4: Run the checks and see them pass.** The e2e suite passes, and `tsc` and `build` are clean.
- [ ] **Step 5: Commit.** `feat(web): Ask page with live trace, answer card, claims and chips`.

### Task 5: Rail, linked selection and charts

**Files:**
- Create:
  - `web/components/rail/answer-rail.tsx`, `web/components/rail/evidence-entry.tsx`;
  - `web/components/charts/vega-chart.tsx`, `web/components/answer/key-chart.tsx`, `web/components/answer/drivers.tsx`, `web/components/answer/recon.tsx`;
  - `web/lib/chart-colors.json`, `web/lib/chart-theme.ts`;
  - `tests/test_chart_colors.py`, `web/e2e/rail.spec.ts`.
- Modify: `web/app/page.tsx`, `web/components/answer/answer-view.tsx`, `web/package.json` (vega-embed, vega, vega-lite).

**Interfaces:**
- Consumes: Task 1's `View.evidence`, `key_charts`, `default_dimension`, `fallback_chart`, `drivers` and `recon`; Task 4's `selectEvidence` and chips.
- Produces:
  - `<AnswerRail bundle view />` with shadcn `Tabs`: "Plan", "Evidence (n)" and "Footprints".
    - **Evidence:** one `EvidenceEntry` per `view.evidence` (`data-testid="evidence-E2"`, `data-selected`). The selected entry expands to show:
      - meta KV;
      - SQL blocks (`<pre>` in Geist Mono with horizontal scroll inside the block, plus a copy button using `navigator.clipboard.writeText` in try/catch);
      - the values table;
      - the result table (the `Table` cells as given);
      - its chart;
      - "Cited by claim 2, 3".
      Selecting it scrolls the entry into view inside the rail only.
    - **Plan:** plan fields as KV and a "Raw JSON" collapsible.
    - **Footprints:** `view.footprint.items` and `stages`, plus `download-bundle`.
  - Claims whose `data-cites` include the selected id get `data-highlight="true"`.
  - `<VegaChart spec />`: client-only (`next/dynamic`, `ssr: false`). It deep-copies the spec and replaces every string equal, case-insensitively, to a key of `chart-colors.json[theme]` with its value. It embeds with `{actions: false, renderer: "svg", config: chartTheme(theme)}`, uses `width: "container"` where the spec has no width, and re-embeds on theme change.
  - `chart-colors.json` is `{"light": {...}, "dark": {...}}` with keys `#D55E00, #009E73, #0072B2, #E69F00, #595959, #000000, #BBBBBB, #CC79A7, #56B4E9, #F0E442`:
    - light values: `#C22F2A, #167A3C, #2456C4, #A86A00, #5A5E66, #111214, #B9BCC2, #A23B7A, #2F86C5, #8C7A00`;
    - dark values: `#FF7B74, #5ED18E, #7FA8FF, #E3A93C, #9A9EA7, #EDEEF0, #4A4E56, #E58BBE, #6EC1F0, #E8D85A`.
  - `chartTheme(theme)` returns a Vega config: background transparent, Geist font, axis and legend label and title colours from muted, grid and domain colours from border, and default `text` mark fill from text.
  - `<KeyChart view />`: a "Decompose by" `Select` over `key_charts` (default `default_dimension`), the chart, the Simpson callout (`data-testid="simpson"`), the summary and `drivers.notes`. Otherwise the recon bridge, or the `fallback_chart`.

- [ ] **Step 1: Write the failing pytest `tests/test_chart_colors.py::test_map_covers_every_chart_colour`.** Collect `re.findall(r"#[0-9A-Fa-f]{6}", Path("sherpa/charts.py").read_text())`; each one, upper-cased, must be a key of both themes in `web/lib/chart-colors.json`, and the two themes must have identical key sets.
- [ ] **Step 2: Write the failing `web/e2e/rail.spec.ts`:**
  - `chip opens evidence in the rail and highlights citing claims`:
    - ask explain_change, then click `chip-E2`;
    - `evidence-E2` has `data-selected="true"` and contains `SELECT`;
    - every claim with `E2` in `data-cites` has `data-highlight="true"`, and the others do not.
  - `charts render`: at least 2 `svg.marks` (the key chart plus an evidence chart) are visible after selecting an evidence entry with a chart; `simpson` contains "Simpson".
  - `decompose by switches the chart`: choosing the second option of the select changes the `simpson` or summary text.
  - `reconcile renders bridge and components`: ask "Why doesn't settled amount match GMV for the last 7 days?"; the text "Reconciliation components" is visible and an `svg.marks` is visible.
  - `sql_route table shows injection verbatim`: chip `E1` shows the injection string inside a `td`, and `document.querySelectorAll("img").length` is unchanged from before the ask.
  - `no page overflow on sql_route`: `document.documentElement.scrollWidth <= window.innerWidth` at 1400 and at 1100.
  - `narrow screen: chip opens the sheet`: at 1100×900, clicking `chip-E2` opens `rail-sheet` showing `evidence-E2`.
  - `dark theme recolours charts`: after the theme toggle switches to dark, no `svg.marks [fill="#D55E00"]` remains.
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement the rail.** Add vega-embed: run `pnpm -C web view vega-embed time --json` and pick the newest version older than 14 days, then the matching vega and vega-lite. Then implement the components above.
- [ ] **Step 5: Run the checks and see them pass.** `uv run pytest tests/test_chart_colors.py -q` passes, the e2e suite passes, and `tsc` and `build` are clean.
- [ ] **Step 6: Commit.** `feat(web): inspector rail with linked evidence, themed Vega charts, drivers and recon`.

### Task 6: Clarification, refusal, error states, and Explore

**Files:**
- Create: `web/components/answer/states.tsx`, `web/components/explore/explore-form.tsx`, `web/e2e/states.spec.ts`, `web/e2e/explore.spec.ts`
- Modify: `web/app/page.tsx`, `web/app/explore/page.tsx`, `web/components/answer/answer-view.tsx`

**Interfaces:**
- Consumes:
  - Task 2's `POST /api/explore/plan` and `ask(..., {plan, patch})`;
  - `meta.catalog`;
  - Task 4 and Task 5 components.
- Produces:
  - `<BundleView bundle view />`, which switches on status: `error` → `ErrorCard`, `clarify` → `Clarification`, `refused` → `RefusalCard`, otherwise `AnswerView`. Both the Ask and Explore pages use it.
  - **Clarification:** `c.question`, "Your question: …", and one button per option labelled `label · preview` (`data-testid="clarify-option"`, disabled when `bundle.plan` is null). Clicking calls `ask(bundle.question, {plan: bundle.plan, patch: option.plan_patch, persona: bundle.persona})`.
  - **Refusal:** "Not answered", the reason, the suggestion, and a "Show me that instead" button (`data-testid="refusal-accept"`) when `refusal.plan_patch && bundle.plan`. It also shows `Run <id> · persona <p>`.
  - **ErrorCard:** "This run failed.", the error text, "Question: …", and the run id in a `<code>` with a copy button.
  - **Explore:**
    - the form: intent `Select`, metric `Select`, dimensions `ToggleGroup type="multiple"` (only the dimensions whose `tables` include `metric.table`), window `Select`, baseline `Select` (only for `compare_periods` and `explain_change`), grain (only for `trend`), and a filter dimension multi-toggle with a value multi-toggle per chosen dimension;
    - every change calls `explorePlan` (debounced 250 ms) and shows "Question: …";
    - the rail shows the plan as KV plus raw JSON (`data-testid="plan-json"`);
    - "Run plan" calls `ask(question, {plan})`, and the result renders below the form with `BundleView` and the answer rail.

- [ ] **Step 1: Write the failing e2e tests:**
  - `clarification options show previews and answer`: ask "What was the success rate yesterday?"; there are 2 `clarify-option` elements whose text contains `%`; clicking the first shows `headline`.
  - `refusal card and suggested plan`: persona `rm_south`, ask "Compare North vs South success rate"; the text contains "out of scope"; clicking `refusal-accept` shows `headline`.
  - `error card keeps run id`: `/?q=x&fixture=error` shows `error-card` containing "This run failed" and `fx-error-0001`.
  - `partial bundle renders`: `/?q=x&fixture=partial` shows `headline`, the text "E9 · not in this bundle", and no console errors (`page.on("pageerror")`).
  - `explore builds a catalog plan and runs it`:
    - choose dimension `payment_method`, filter `region` = `South`;
    - `plan-json` contains `"route": "catalog"`, `"payment_method"` and `"South"`;
    - "Run plan" leads to `headline`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the states and Explore.**
- [ ] **Step 4: Run the checks and see them pass.** The full e2e suite is green.
- [ ] **Step 5: Commit.** `feat(web): clarification, refusal and error states; Explore page`.

### Task 7: Eval and Runs pages

**Files:**
- Create: `web/components/eval/eval-view.tsx`, `web/components/runs/runs-view.tsx`, `web/e2e/pages.spec.ts`
- Modify: `web/app/eval/page.tsx`, `web/app/runs/page.tsx`

**Interfaces:**
- Consumes: Task 2's `GET /api/eval` and `GET /api/runs`, and Task 3's `Workspace`.
- Produces:
  - **Eval:**
    - 7 tiles (`data-testid="eval-tile"`), each showing label, Sherpa value and "baseline …";
    - "Generated … · data …";
    - a fixture-mode notice when `fixture`;
    - a cases table (`data-testid="eval-cases"`) with pass/fail shown as icon plus text, never colour alone;
    - selecting a row shows the case details in the rail;
    - `missing` and `error` statuses render explanatory text.
  - **Runs:** 7 tiles (`run-tile`) and a recent table (`runs-table`); selecting a row shows its `footprint` KV in the rail. `unavailable` renders the message (`runs-unavailable`).

- [ ] **Step 1: Write the failing `web/e2e/pages.spec.ts`:**
  - `eval shows 7 tiles and the cases table`.
  - `eval case opens in the rail`.
  - `runs shows tiles or a clear unavailable message`: either 7 `run-tile`s, or `runs-unavailable` visible.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement the two pages.**
- [ ] **Step 4: Run the checks and see them pass.**
- [ ] **Step 5: Commit.** `feat(web): Eval and Runs pages`.

### Task 8: Docker, Streamlit removal, docs, and the live check

**Files:**
- Create: `web/Dockerfile`, `web/.dockerignore`
- Modify:
  - `Dockerfile`: CMD becomes uvicorn `app.api:app` on `0.0.0.0:8000`; EXPOSE 8000.
  - `docker-compose.yml`:
    - `api` service replaces `app` (no host port);
    - `web` service: build `./web`, env `SHERPA_API_URL=http://api:8000`, ports `127.0.0.1:3000:3000`, `depends_on` api.
  - `Makefile`, `pyproject.toml`, `uv.lock`: remove streamlit; move altair to dev.
  - Docs: `README.md`, `docs/DEMO.md` (port 3000 and new UI steps), `docs/ARCHITECTURE.md` (UI layer), `docs/CONTRACTS.md` §0 (`app/` and `web/` owned by ui), `docs/TASKS.md` (UI rebuild rows), `CLAUDE.md` (stack and app command).
- Delete: `app/streamlit_app.py`, `app/render.py`, `.streamlit/`, `tests/test_app.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the final branch state, ready to merge.

- [ ] **Step 1: Delete Streamlit and update dependencies.** Delete the Streamlit files, then run `uv remove streamlit && uv remove altair && uv add --dev altair`. Check with `grep -rn "streamlit" --include=*.py . | grep -v .venv`: it should find nothing outside docs.
- [ ] **Step 2: Write the Docker files.** `web/Dockerfile` is multi-stage `node:26-slim`: corepack pnpm, `pnpm install --frozen-lockfile`, `pnpm build`, then the runner copies `.next/standalone`, `.next/static` and `public`; CMD is `node server.js` with `HOSTNAME=0.0.0.0 PORT=3000`. Then update the compose file. Verify with `docker compose config -q`, which should exit 0. **Do not run `docker build`.**
- [ ] **Step 3: Update the docs.** In the README, replace the Streamlit run instructions with `make api` and `make web` (or `make app`) and `http://localhost:3000`, and add a line saying the Docker files were not built here because of disk limits. Update the other docs as listed under Files.
- [ ] **Step 4: Run the full verification.**
  - `uv run pytest -q` should be all green, with `test_app.py` gone and `test_api.py`, `test_view.py`, `test_backend.py` and `test_chart_colors.py` present.
  - `pnpm -C web exec tsc --noEmit`, `pnpm -C web lint` and `pnpm -C web build` should all be clean.
  - `pnpm -C web e2e` should be all green.
- [ ] **Step 5: Run the live smoke test with the real pipeline and claude-cli.**
  - Start `make api` (without `SHERPA_UI_FIXTURES`) and `pnpm -C web start -p 3000` after building with the default API URL.
  - With Playwright, ask "Why did success rate drop last week?".
  - Check that the headline appears, and that `data-stage-times` has at least 4 entries with the first more than 1000 ms before the result arrives (Review Focus 1).
  - Save screenshots in light and dark to `docs/img/ui-light.png` and `docs/img/ui-dark.png`.
  - If the stages arrive buffered, add a `web/app/api/ask/route.ts` handler that pipes `fetch(SHERPA_API_URL + "/api/ask")`'s body through as a stream, and re-run.
- [ ] **Step 6: Commit.** Use one commit per concern: `chore: remove Streamlit UI`, `build: api and web compose services (not built here)`, `docs: Next.js UI in README, DEMO, ARCHITECTURE, CONTRACTS, TASKS`.
