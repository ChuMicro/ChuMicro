# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **scripts/workbench/template-repo audit — gaps-doc cleanup landed.**  End-to-end re-audit of how `scripts/`, `workbench/*` packages, and the `ChuMicro-Workspace-Template` repo intersect.  Confirmed gaps-doc items #1 (cryptography) + #2 (doc links) landed as `8bcfb6b`/`d9d039e` (struck through in the doc), and verified gap #6 (`add-device` defaults) still open in code.  Two new architectural observations surfaced beyond the existing gaps doc, queued as follow-ups: (a) `chumicro_deploy._runtime_marker` is private-by-name but public-by-Decision-0044 with three external callers (scripts/bundle_manager.py, workbench/pytest-device, workbench/workspace.boot_shim) — promote to `runtime_marker` and re-export; (b) `scripts/workspace.py` shares its module name with the `chumicro_workspace` package (18 sibling `from workspace import …` callsites) — rename to `scripts/repo_layout.py`.  My initial recommendation to fold `prepare_workspace.py` into `scripts/run.py` was already considered and rejected (Item B in `plans/next-up.md` L52, commit `318516a` — split is load-bearing, not cosmetic).
- **Last shipped:** `plans/workspace-template-dev-and-regular-mode-gaps.md: strike landed items, confirm gap #6 still open` (this commit).
- **In flight:** idle.  Two audit follow-ups awaiting user pick: `_runtime_marker` promotion (3 external callers + Decision 0044 prose), `scripts/workspace.py` → `scripts/repo_layout.py` rename (18 importers).
- **Blocked on:** —.
- **Last touched:** `plans/workspace-template-dev-and-regular-mode-gaps.md`, `plans/now.md`.

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
