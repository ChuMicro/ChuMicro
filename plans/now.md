# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **scripts/workbench/template-repo audit — module-name collision resolved.**  Third cleanup pass from the cross-tree audit: renamed `scripts/workspace.py` -> `scripts/repo_layout.py` (and the test file `test_workspace.py` -> `test_repo_layout.py`) via `git mv` to disambiguate from the `chumicro_workspace` workbench package.  18 sibling scripts in `scripts/` updated to `from repo_layout import …`; `audit_gates.py`'s bare `import workspace` + dotted access; the renamed test file's bare import + `from` import + `monkeypatch.setattr(workspace, …)` patches; lazy imports inside `test_bundle_manager.py`; docstring prose in `repo_layout.py`, `test_ide_sync.py`, and Decision 0032.  Conceptual prose ("workspace state", "workspace fixture") left as-is — those refer to the mono-repo concept, not the module.  No VERSION bumps — `scripts/` is mono-repo internal, not published.
- **Last shipped:** `scripts: rename workspace.py -> repo_layout.py to disambiguate from chumicro_workspace package` (this commit).
- **In flight:** idle.  Audit follow-up queue from `plans/workspace-template-dev-and-regular-mode-gaps.md` is the natural next; the three cleanup items I queued are now all landed (`326651e` gaps-doc strike, `96bddcd` runtime_marker promotion, this commit).
- **Blocked on:** —.
- **Last touched:** `scripts/{repo_layout.py,run.py,*.py}`, `scripts/tests/{test_repo_layout.py,test_bundle_manager.py,test_ide_sync.py}`, `plans/decisions/0032-workbench-host-tools.md`, `plans/now.md`.

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
