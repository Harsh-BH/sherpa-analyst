# 3-minute demo script

Setup: `make up && make seed`, `pnpm -C web install` once, `make app`, browser at http://localhost:3000, persona **Business head**
(sidebar). Pick light or dark with the theme toggle before recording.
The `claude` CLI must be logged in, or `ANTHROPIC_API_KEY` set. Each Ask takes about 15–25 s (planner plus narrator), so either cut
the waits in the edit or use pre-run answers: re-asking a question hits the query cache, and the **Runs** page shows the timings.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Title slide or README hero | "Leaders ask *why did success rate drop?* An LLM writing SQL gets this wrong when the real answer is that the mix changed. Sherpa lets the LLM plan and narrate, and lets code compute." |
| 0:15 | Ask: **Why did success rate drop last week?** Show the live trace: each stage (plan, triage, analysis, dq, narrate, check) appears with its elapsed time, then folds into one line of steps, time and cost. | "The model turns the question into a typed plan; the catalog compiles it to SQL that runs under my own database role." |
| 0:35 | Answer: headline, confidence and route badges, **Simpson's paradox** callout, waterfall (switch "Decompose by" to show another dimension) | "Overall −0.84 pp, but −0.92 pp is mix and +0.08 pp is rate. UPI's share went from 45% to 58%, and UPI's own success rate didn't move. Nothing got worse." |
| 0:55 | Click a Fact's **E2** chip: the rail's **Evidence** tab opens that entry (SQL, window, filters, hash) and every claim citing it is highlighted | "Every number is a placeholder filled from an executed query. The model never types a digit; a checker rejects it if it does, even 'one hour'." |
| 1:05 | Point at the DQ banner above the headline and the Caveat; open **Footprints** for time per stage, LLM cost and the run bundle download | "It also noticed PG_C sent nothing for 6 hours inside the window, and says so before you trust the number." |
| 1:15 | Ask: **Why did success rate fall on 22 Oct compared with the day before?** | "A different shape: one bank's own rate collapsed. EGRET's technical declines went from 0.6% to 9.9%, concentrated at 10:00–16:00. 'Outage' is labelled a hypothesis." |
| 1:40 | Ask: **What was our success rate last week?** | "Ambiguous: with or without customer drop-offs? It computed both, 91.7% vs 85.4%, and asks. When both definitions tell the same story, it just states the assumption." |
| 1:55 | Switch persona in the sidebar to **Regional manager, South**. Ask: **Compare North vs South success rate** | "Out of scope. An explained refusal and a one-click South-only answer, before any SQL runs." |
| 2:10 | (Optional) the terminal: `uv run pytest -k rls_backstop` | "If the app layer had a bug, Postgres row-level security on this login role still returns only South rows. That test bypasses the guard on purpose." |
| 2:20 | Ask: **Why doesn't the settled amount match GMV on 20 Oct?** | "Two sources disagree. The bridge splits the gap into the 23:00 cutoff, refunds and MDR fees, and they add up exactly." |
| 2:35 | **Eval** page (sidebar) | "On two seeds of planted causes, Sherpa against a naive LLM-writes-SQL baseline: 56 of 56 cases against 17 of 56, and zero unsupported numbers against seventy-two." |
| 2:50 | README "Security model" + "Adversarial review" | "An independent multi-agent review tried to break it and found 24 real issues, including a Postgres field-selection trick past the function allowlist. All are fixed with regression tests." |
| 3:00 | End | "Sherpa: every number traced, every guess labelled." |
