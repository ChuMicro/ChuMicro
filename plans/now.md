# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **scripts/workbench audit — env-var-as-arg pushback continued (2c follow-up).**  User asked "ci could provide its own devices.yml?" after noting CI is "a wasteland."  Verified: zero CI workflows reference `CHUMICRO_DEVICES`, `devices.yml` is gitignored, and every production caller passes an explicit path or `workspace_root`.  Sibling `CHUMICRO_DEVICE_CONFIG` was orphaned (docs + ADR referenced it; zero code).  Both env vars deleted.  `_resolve_devices_path()` simplified to just `<workspace_root>/devices.yml`.  Three test cases that exercised the env var dropped (one in `workbench/deploy/tests/test_device_registry.py`; the three pytest-device cases now rely on `_FakeSession(rootpath=tmp_path)` which already pointed at the right path).  Docs section §9 rewritten: "CI just drops a devices.yml at the workspace root."  ADR 0027 line 22 strikethroughed with a 2026-05-03 deletion note.
- **Last shipped:** `workbench/deploy + workbench/pytest-device + docs: drop CHUMICRO_DEVICES env var (anticipatory, no live consumers)` (this commit).  Earlier today: `49fb45e` (CHUMICRO_PARALLEL_* env vars dropped for `--phase-workers` / `--package-workers` / `--max-workers` flags), `ed6b595` (`scripts/workspace.py` -> `scripts/repo_layout.py`).
- **In flight:** idle on my side.  Note: there's pre-existing uncommitted WIP from a parallel session on `chumicro_workspace.boot_shim` (new file + tests + VERSION bump in `workbench/workspace/`); not mine, left alone.
- **Blocked on:** —.
- **Last touched:** `workbench/deploy/{src/chumicro_deploy/config/default.py,tests/test_device_registry.py}`, `workbench/pytest-device/tests/test_plugin.py`, `docs/contributing/device-testing.md`, `plans/decisions/0027-device-testing-infrastructure.md`, `plans/now.md`.

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
