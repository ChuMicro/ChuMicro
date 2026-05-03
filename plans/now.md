# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **pytest-device runtime-marker support — done.**  Functional tests for runtime-specific backends (CP NVM, MP LittleFS / NVS, CP / MP wifi adapters) were generating 34 spurious `ImportError`s every full `test-libraries-functional` sweep when `defaults.ide_runtime: both` parametrized them with the wrong runtime.  Plugin now reads each test file's `__chumicro_runtimes__` marker (same convention as device-side source files per Decisions 0037 / 0044) and filters target devices accordingly; a second hook (`pytest_pycollect_makemodule`) returns a no-import stub for `libraries/<name>/functional_tests/test_*.py` paths so pytest's default Module factory never tries to import them on the host.  Five test files lost their dead `if not _IS_X: return` short-circuits in the same commit.
- **Last shipped:** `chumicro-pytest-device + kvstore/wifi functional tests: honor __chumicro_runtimes__ marker; suppress host-side Module collection` (this commit).  Validated against pi-pico-w MP + CP boards: kvstore 43 passed (was 22 spurious ImportErrors), wifi 41 passed (was 13 spurious ImportErrors).
- **In flight:** idle.
- **Blocked on:** —.  Pre-existing `test_pre_release_floor_skips_bump_requirement` failure flagged via spawn_task — not in scope for this slice.
- **Last touched:** workbench/pytest-device/{src,tests}, libraries/{kvstore,wifi}/functional_tests/, plans/now.md.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Anything in `## Next` of `next-up.md` | `plans/next-up.md` | Rebrand to ChipPy, OTA workstream (`plans/workstreams/ota.md`), digital I/O library, performance benchmarking infrastructure, etc.  All are unscoped or trigger-gated. |

## Hard rules to remember (non-negotiables)

- **`AGENTS.md` non-negotiables apply.**  Read it on session start.
- **No backward compatibility burden.**  Nothing's published to PyPI yet — change formats, flags, layouts freely.  Do not add migration logic.
- **Task-checkpoint per slice.**  Every coherent unit ends with green preflight (`python scripts/run.py preflight --coverage-threshold 94`) + commit + push.
- **`git commit -F .scratch/commit-msg.txt`** — write the message to a file via Write tool, then `git commit -F`.  No `-m`, no heredocs in the terminal.  No `Co-Authored-By: Claude` trailer.
- **Two-repo flow.**  The mono-repo is at `/Users/chuxor/circuitpython/chumicro`; the workspace template repo is at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`.  Several workstreams touch both.
- **Branching policy.**  Repo is private — commit directly to `main`; no PRs.
- **All four boards plugged in.**  `devices.yml` registers Lolin S2 (CP+MP) and Pi Pico W (CP+MP).  Hardware-functional tests are runnable via `python scripts/run.py test-workbench-functional` / `test-libraries-functional`.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
