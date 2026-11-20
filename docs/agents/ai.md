# Brief: ai agent (LLM backend, planner, triage, narrator + claim checker)

The model's two jobs are **question → typed AnalysisPlan** and **evidence → tagged claims**. Everything
around the model makes those jobs safe and checkable.

**You own:** `sherpa/llm.py`, `sherpa/planner.py`, `sherpa/triage.py`, `sherpa/narrate.py`, `sherpa/prompts/`
(prompt text files if you want them), `tests/test_llm.py`, `tests/test_planner.py`, `tests/test_triage.py`,
`tests/test_narrate.py`. Signatures: docs/CONTRACTS.md §4. Types: `sherpa/contracts.py`.
Before writing any Anthropic SDK code, **invoke the `claude-api` skill** and follow it. Do not guess
SDK shapes (structured outputs, adaptive thinking, prompt caching and model ids all changed recently).

## Tasks

**L1: `llm.py`.** `backend()` resolves `settings().llm_backend`:
- `auto` picks `anthropic` if `ANTHROPIC_API_KEY` is set, else `claude-cli` if `claude` is on PATH, else `none`.
- `structured(...)` returns `(json_dict, usage)`.
- **anthropic:** the official SDK with JSON-schema structured output, the system prompt marked for prompt caching, and adaptive thinking where the skill says it applies.
- **claude-cli:** `subprocess.run(["claude", "-p", "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema), ...], input=user)`. Read `structured_output` and `usage` / `total_cost_usd` from the JSON result.
  - Verified locally: `claude -p --output-format json --json-schema '<schema>' "<prompt>"` returns `{"structured_output": {...}, "total_cost_usd": ..., "usage": {...}, "is_error": false}` in ~5 s on haiku.
  - Find the flags that strip it to a plain completion (check `claude --help`: `--system-prompt`, `--tools`, `--no-session-persistence`, `--bare`, `--exclude-dynamic-system-prompt-sections`), so it doesn't load the coding-agent context.
  - Timeout 180 s. Raise `LLMUnavailable` on failure, with stderr trimmed.
- **none:** raise `LLMUnavailable`.
- Validate the returned dict against the schema's required keys before returning; the CLI path can return text.

**L2: `planner.plan`.**
- **System prompt**, built from `load_catalog()` and stable across personas and questions so it caches:
  - metrics with descriptions, synonyms and variants; dimensions with values and synonyms
  - window presets and what they mean
  - intents
  - routing rules:
    - **catalog** when catalog metrics and dimensions express the question
    - **sql** only when they can't; then write one Postgres SELECT over the `analytics.*` tables and columns in `db/access.yaml`, using IST dates
    - **clarify** when a required choice has no safe default
    - **refuse** for questions the data cannot answer (forecasts, PII, other companies, actions) or that explicitly target data outside the persona's regions
  - assumption rules: always state how a vague period was read
  - verified queries as few-shot examples (question → plan JSON)
- **User message:** the question, persona label and regions, `as_of`, `data_start`, and resolved dates for each preset, so the model never does date arithmetic.
- **JSON schema:** from `AnalysisPlan.model_json_schema()`, with `metric`/`dimensions`/`filters.dimension` constrained to catalog names (enum) and presets enumerated. Make sure the schema is accepted by both backends (test it live once).
- **Validation:** with pydantic.
- **Denominator rule:** when the question says "success rate" without pinning the denominator, add an `Ambiguity(kind="denominator", options=[metric, *variants])` and still pick the default metric. The pipeline computes both and asks only if they differ by more than 0.3 pp.

**L3: `triage.triage`** (pure, deterministic).
- Unknown metric or dimension names → clarify, with close matches (difflib) as options (`ClarifyOption.plan_patch`).
- Filter values are normalised case-insensitively against vocabularies ("upi" → "UPI", bank names "Kestrel Bank" → "KESTREL"). Unknown values → clarify.
- Dimensions not on the metric's table → clarify.
- A filter or explicit question scope on regions outside `persona.regions` → **refuse**, with a reason naming the region and the persona's scope. The suggestion offers the same question limited to their regions, as `Refusal.suggestion`, plus a `Clarification` with a plan_patch the UI can apply. For `head`, nothing is out of scope.
- Fill missing windows: `last_7_days`, and for compare/explain the baseline defaults to the preceding window. Each default adds an assumption sentence.
- `route == "sql"` without `sql` → clarify. Route clarify/refuse from the planner passes through.
- `variant_metrics` = the denominator ambiguity's other options.
- Test every branch.

**L4: `narrate.py`.**
- **`sanitize`:**
  - Evidence goes to the model as id, kind, title, window, baseline, filters, numeric `values` with their formats, and table rows reduced to closed-vocabulary dimension values and numbers.
  - Drop rows whose denominator-like count is under `MIN_SUPPORT`.
  - Never pass free-text strings: anything not in a catalog vocabulary or an id pattern becomes `"<redacted>"`. Never pass `display_name`.
  - Test: an Evidence whose table contains S6's injection string produces sanitized output without it.
- **`narrate`:**
  - The model returns a `Narrative`.
  - Rules: every number as `{E<n>.<key>}` and only keys that exist; facts must cite evidence ids; mechanisms ("issuer outage", "new merchant onboarding") are hypotheses; recommendations are concrete and owned; caveats repeat DQ warnings and assumptions; at most 7 claims; a plain headline.
  - After `check_claims`, if any claim has problems, run **one** repair call listing them, then keep only claims that pass.
- **`template_narrative`:** a deterministic no-LLM narrative covering explain_change (Simpson-aware wording), breakdown, trend, compare, reconcile, data_quality and metric_value. Explore mode and the eval baseline comparison use it when there's no LLM.
- **`check_claims`:**
  - Resolve placeholders with `contracts.format_value`.
  - **Reject** a claim if it has a standalone numeral outside placeholders (regex; allow digits inside identifiers such as `PG_A`, `T1`, `3DS`, `S1`), an unknown evidence id or key, or a fact citing no evidence.
  - Return the rendered headline. A headline with a bad placeholder falls back to a safe generic headline.
  - Test with a fabricated number ("SR fell to 85%") → rejected.
- **`confidence`:** rule-based, with each reason a short sentence.
  - The sql route caps confidence at medium.
  - A DQ error in the window lowers it one level, and a DQ warn notes it.
  - A top driver dimension with no supported significant segment → medium.
  - Dropped claims lower it one level.
  - Small denominators → low.
  - An assumption-driven window or denominator adds a reason.

## Acceptance
- All unit tests pass without any LLM, using monkeypatched `structured`.
- Exactly 3 `@pytest.mark.live` tests: the planner on "Why did success rate drop last week?" (expects explain_change, success_rate, last_7_days vs previous_7_days); the planner on "Compare North vs South success rate" as `rm_south` (expects refuse, or triage refuses); and narrate + check_claims on a fixed evidence set (expects all claims ok).
- Run them once on the claude-cli backend and paste the results and costs in your report.
