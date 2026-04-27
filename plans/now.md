# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace-template testing-infrastructure audit COMPLETE 2026-04-27**.  Audited the `ChuMicro-Workspace-Template` repo, found big gaps vs the chumicro mono-repo's CI surface (no `tests/` starter, no lint config, no coverage gate, no `.github/workflows/`, no `chumicro-pytest-device` adoption), and shipped Phase A to the template repo + Phase B to chumicro to close them.  Pick the next workstream from `plans/next-up.md`'s `## Next` queue.
- **Last shipped:**
  * **Template repo `579274a`** — Phase A: `[tool.ruff]` config + `[tool.coverage.report] fail_under = 85` + `[project.optional-dependencies] dev` (pulls `chumicro-pytest-device`, `pytest`, `pytest-cov`, `ruff`).  New `tests/test_workspace.py` (parametrized "every thing exposes `run()`" smoke test + `workspace.yml` parses).  New `things/_template/tests/test_app.py` so `python run.py new <name>` scaffolds a starter test.  New `.github/workflows/test.yml` running setup + lint + test on push/PR across Python 3.11/3.12/3.13.  `AGENTS.md` "Tests + lint" section + commands-table refresh.  3 tests, all pass; ruff config clean.
  * **chumicro `f47acba`** — Phase B: `chumicro-workspace lint` command shells out to `ruff check .` from the workspace root, with `--`-passthrough for `--fix` etc.  Skips with a discoverable hint when ruff isn't installed.  3 new `TestLintCommand` tests.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** Mono-repo: `workbench/workspace/src/chumicro_workspace/cli.py` (`_cmd_lint` + parser registration), `workbench/workspace/tests/test_cli.py` (`TestLintCommand`).  Template repo (separate git): `pyproject.toml`, `tests/test_workspace.py` (new), `things/_template/tests/test_app.py` (new), `.github/workflows/test.yml` (new), `AGENTS.md`, `things/example_sensor/app.py` (single-blank-line ruff-fix).

---

## What this round closed (audit findings → shipped)

| Audit gap | Status |
|---|---|
| No `tests/` starter | ✅ `tests/test_workspace.py` (parametrized over things) |
| No `python run.py lint` | ✅ `chumicro-workspace lint` command (mono-repo Phase B) |
| No `[tool.ruff]` config in template | ✅ Mirrors mono-repo's tone (line-length 100, py311, `select = E F I B UP TID252`) |
| No coverage gate | ✅ `[tool.coverage.report] fail_under = 85` (soft default) |
| No GitHub Actions CI | ✅ `.github/workflows/test.yml` (setup + lint + test, 3.11/3.12/3.13 matrix) |
| `chumicro-pytest-device` not a dep | ✅ Declared in `[project.optional-dependencies] dev` — auto-registers via `pytest11` entry point on install |
| `things/_template/` lacks test scaffolding | ✅ `things/_template/tests/test_app.py` ships with the starter scaffold |

## What's pending (one open follow-up)

`chumicro-pytest-device` 0.1.0 hasn't been published to PyPI yet (it just landed in the mono-repo).  Once published, external workspaces' `python run.py setup` will pull it via the `dev` extra automatically.  Until then, `chumicro-dev` mode picks it up via the editable install.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
