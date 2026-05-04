# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **scripts/workbench/template-repo audit — runtime-marker promotion landed.**  Second cleanup pass from the cross-tree audit: `chumicro_deploy._runtime_marker` was private-by-name but designated by Decision 0044 as a public cross-package contract (3 external callers in scripts/bundle_manager.py, workbench/pytest-device, workbench/workspace.boot_shim).  Renamed to `chumicro_deploy.runtime_marker`, re-exported `read_runtime_marker` + `file_targets_runtime` from `chumicro_deploy.__init__`, updated all 7 callers (4 internal, 3 external) + test module + Decision 0044 prose.  VERSION bumps: deploy 0.5.0 → 0.6.0 (minor — new public surface), pytest-device 0.3.1 → 0.3.2 (patch — consumer path), workspace 0.3.0 → 0.3.1 (patch — consumer path).
- **Last shipped:** `chumicro-deploy + chumicro-pytest-device + chumicro-workspace: promote _runtime_marker to public chumicro_deploy.runtime_marker` (this commit).
- **In flight:** idle.  One audit follow-up still queued: rename `scripts/workspace.py` → `scripts/repo_layout.py` to kill the module-name collision with the `chumicro_workspace` package (18 sibling `from workspace import …` callsites + bare `import workspace` in `audit_gates.py`).
- **Blocked on:** —.
- **Last touched:** `workbench/deploy/{src,tests,VERSION}`, `workbench/pytest-device/{src,tests,VERSION}`, `workbench/workspace/{src,VERSION}`, `scripts/bundle_manager.py`, `plans/decisions/0044-deploy-time-runtime-filtering.md`, `plans/now.md`.

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
