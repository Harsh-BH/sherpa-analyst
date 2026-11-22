# Demo script (about 3:45)

The submission allows a 2–5 minute video. This script runs about 3:45 and shows every failure scenario in the brief.

## Setup

1. `make up && make seed`, `pnpm -C web install` once, then `make app`. Open http://localhost:3000 with persona
   **Business head** selected in the sidebar.
2. The `claude` CLI must be logged in, or `ANTHROPIC_API_KEY` set. Each Ask takes 15–25 s and costs about $0.19, so the
   whole script costs about $1.20.
3. **Pre-run the answers.** Ask every question once before recording. During the recording, either ask live and cut the
   wait in the edit, or reopen the answer from **Recent** in the sidebar. A reopened run is instant and makes no LLM call.
4. Pick light or dark with the theme toggle (bottom of the sidebar), and set the browser to about 1440 × 900.

## Script

| Time | Screen | Say |
|---|---|---|
| 0:00 | Title slide or the README hero | "Leaders ask *why did success rate drop?* An LLM writing SQL gets this wrong when the real answer is that the mix changed. Sherpa lets the LLM plan and narrate, and lets code compute." |
| 0:15 | **Home**, before asking: the four KPI cards, the daily success-rate chart, the **Data health** rail | "Before I ask anything: the last 30 days, through the same governed queries as an answer, and no LLM. The rail has already found PG_C's six-hour gap on 16 Nov and PG_B's duplicate webhooks." |
| 0:30 | Ask **Why did success rate drop last week?** Watch the trace: each stage appears with a timing bar. The chart, the DQ banners and the segment tables appear first, while "Writing the summary…" shimmers. | "The model turns the question into a typed plan; the catalog compiles it to SQL that runs under my own database role. The numbers arrive first, while the summary is still being written." |
| 0:50 | The answer: headline chips (92.5% → 91.7%), the **Simpson's paradox** callout, the waterfall | "Down 0.84 points, but minus 0.92 is mix and plus 0.08 is rate. UPI's share went from 45% to 58%, and UPI's own success rate didn't move. No method got worse." |
| 1:05 | Click a Fact's **E2** chip: the rail's **Evidence** tab opens that query (SQL, hash, window, filters) and every claim citing it is highlighted | "Every number is a placeholder filled from an executed query. The model never types a digit; a checker rejects it if it does, even 'one hour'." |
| 1:15 | Point at **Ask next** and the drill links under the waterfall (UPI, CARD…), and **Copy answer** | "Follow-ups come with their own plans, any bar drills into its segment, and the answer copies as Markdown." |
| 1:20 | Click **Ask** in the sidebar to go home, then click the **22 Oct** dip on the trend | "Click any day to ask why it moved. This one is a different shape: EGRET bank's technical declines went from 0.6% to 9.9%, concentrated at 10:00–16:00. 'Outage' is labelled a hypothesis, with a recommendation." |
| 1:45 | Ask **What was our success rate last week?** | "Ambiguous: with or without customer drop-offs? It computed both, 91.7% vs 85.4%, and asks. When both definitions tell the same story, it just states the assumption." |
| 2:00 | Press **⌘K** (Ctrl K), type "south", pick **Regional manager, South**. Ask **Compare North vs South success rate**. | "Out of scope. An explained refusal and a one-click South-only answer, before any SQL runs." |
| 2:15 | (Optional) the terminal: `uv run pytest -k rls_backstop` | "If the app layer had a bug, Postgres row-level security on this login role still returns only South rows. That test bypasses the guard on purpose." |
| 2:25 | Switch back to Business head. Ask **Why doesn't the settled amount match GMV on 20 Oct?** | "Two sources disagree. The bridge splits the gap into the 23:00 cutoff, refunds and MDR fees, and they add up exactly." |
| 2:40 | Click the first run under **Recent**; click **Copy link** and thumbs up | "Every answer is saved for the persona that asked it. It reopens instantly from a permalink, with no LLM call, and the rating goes to the run log." |
| 2:50 | **Eval** page | "On two seeds of planted causes, Sherpa against a naive LLM-writes-SQL baseline: 56 of 56 cases against 17 of 56, and zero unsupported numbers against seventy-two." |
| 3:05 | **Runs** page | "Latency, LLM cost, cache hits and how many answers people found helpful, from the app's own runs. Test traffic is labelled and left out." |
| 3:15 | (Optional) browser dev tools, phone size: the compact top bar, **Inspector** opens the rail as a bottom sheet | "The same answer works on a phone." |
| 3:25 | README "Security model" and "Adversarial review" | "An independent multi-agent review tried to break it and found 24 real issues, including a Postgres field-selection trick past the function allowlist. All are fixed with regression tests." |
| 3:40 | End | "Sherpa: every number traced, every guess labelled." |

## If something goes wrong on camera

- **No LLM:** start with `SHERPA_LLM_BACKEND=none make app`. Explore still works, and pre-run answers still reopen from Recent.
- **No database:** `SHERPA_UI_FIXTURES=1 make api` plus `make web` serves saved answers. The sidebar says "Fixture mode",
  and the fixture's numbers are the unit-test example (92.8% → 91.7%), not the seeded data.
