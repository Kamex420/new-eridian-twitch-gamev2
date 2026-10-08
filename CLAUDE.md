# Working on New Eridian v2

Read by every Claude session in this repo. The owner, Kamex, has a weekly token limit: keep sessions lean.

## How each session runs (orchestrator)

The main session plans, decides and reports; it hands work to helper agents (the Agent tool's `model` option) when the
task is big enough to save tokens. For a quick search or a two-line check, just do it directly.

- **Haiku:** light, mechanical work: finding files and code, confirming a file or value exists, checking a diff's size
  or a format, reading test or CI output for pass/fail.
- **Sonnet:** hands-on work once the plan is settled: implementing, modifying, replacing, running conversions and tests.
  Debugging unexpected failures goes to Sonnet first, Opus if it gets stuck.
- **Opus:** judgment: planning and design choices, reviews of code for correctness (never Haiku), player-facing text,
  release notes and docs, organizing structure.

Give each helper a complete, self-contained brief (files, goal, what to report back) and ask for a short report, not
file dumps. One task per session: when a task is done, suggest starting a new session for the next one.

## Shipping: push to main when the tests pass

Main is what players get (Railway deploys it), so only tested commits reach it:

1. Branch from `origin/main` (`claude/<topic>`), make the change, add or update tests.
2. Run the related tests, then the full suite (`python -m pytest -q`); compare failures against the known
   sandbox-only ones before calling anything broken.
3. Add a short entry at the top of `docs/releases.md` (player-facing, plain words).
4. Commit, push the branch, wait for GitHub's Tests workflow (`gh run watch <id> --exit-status`).
5. When it passes, fast-forward main: `git fetch origin main && git merge-base --is-ancestor origin/main HEAD && git push origin HEAD:main`.

Kamex has asked for this to happen without asking each time, as long as the tests pass.

## Code map

- `docs/architecture.md`: what each module holds, and "Dependencies on app.main" (the explicit-imports project:
  `scripts/explicit_imports.py` converts a system, `python -m scripts.main_dependencies --write` updates the record).
  Left to convert: `workbench`, `autonomy`, `menu` (they also reach app.main through `self.m` / `c.m`).
- `docs/persistence.md`: every table. `docs/releases.md`: what changed, newest first.
- Game rules Kamex decided: no DMs to players asking for event help; Seedlings keep at most 25 Contribution a day.
