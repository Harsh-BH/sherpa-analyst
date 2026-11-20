# Agent protocol (every agent follows this)

You are one engineer on a 5-agent team run by a master agent. Read, in order: `CLAUDE.md`,
`docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `sherpa/contracts.py`, then your brief `docs/agents/<you>.md`.

## Workspace
- You work in your own git worktree, `/home/harsh1/github-repos/sherpa-analyst.worktrees/<you>`, on branch `feature/<you>`.
- Edit **only the files your brief says you own** (also listed in docs/CONTRACTS.md §0). Never touch another agent's files or the master-owned contracts.
- Run everything with `uv run ...` from your worktree root. The dependencies are already in `pyproject.toml`; do not add any (ask instead).
- `.env` is already in your worktree and gitignored. Never commit it, and never print secrets.

## Shared Postgres
- One database for everyone: `localhost:5433`, container `sherpa-db`. Only the **data** agent seeds or re-applies roles.
- Never run `docker compose down -v`, never drop the database, never `docker system/volume/image prune`, and never pull or build images (the disk is ~97% full).
- Tests that need data are marked `@pytest.mark.db`. They skip themselves until the data agent has seeded.

## Coordination (files, not chat)
`COORD=/home/harsh1/github-repos/sherpa-analyst.worktrees/_coord`
- **Status:** append one line per task transition to `$COORD/<you>.status`:
  `2026-11-21T02:30 Q1 in_progress guard skeleton` (states: in_progress | blocked | in_review | completed).
- **Questions or contract changes:** if a contract is wrong or missing, or you need a file you don't own,
  do not work around it. Append the problem and your proposed change to `$COORD/<you>.questions.md`,
  carry on with work that doesn't depend on it, and check `$COORD/<you>.answers.md` between tasks.
  When the master changes a contract it is committed on `main`; then run `git merge main`.
- **Done:** when every task in your brief is complete:
  1. Run your tests: `uv run pytest tests/<your files> -q` (plus `-m db` ones once the DB is seeded).
  2. Commit.
  3. Write `$COORD/<you>.report.md`: what you built, files, test results (paste the summary line),
     deviations from the contracts, known gaps, and anything the integrator must know.
  4. `touch $COORD/<you>.done`, then stop and wait. The master may send follow-up work in this session.

## Git
- Conventional commits, one logical unit each (`feat(guard): ...`, `test(drivers): ...`). Tests pass before every commit.
- Never push, force, rebase or switch branches; never commit to `main`. The master merges your branch.

## Engineering rules
- Smallest code that works: stdlib → installed deps → a few lines. No abstraction with one implementation, no config for constants.
- Non-trivial logic leaves one runnable check behind (a small `tests/test_*.py`).
- Deliberate shortcuts get a `# ponytail: <ceiling>, <upgrade path>` comment.
- Never weaken validation at trust boundaries (SQL, LLM output, data strings rendered in the UI).
- Live LLM calls only in tests marked `@pytest.mark.live`, and only a handful in total. They use the user's Claude account.
