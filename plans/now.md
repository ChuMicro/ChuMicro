# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Decision 0044 shipped — deploy-time runtime-file filtering.**  Extends Decision 0037's `__chumicro_runtimes__` marker filter from the bundle pipeline to *every* host-side deploy path (`chumicro_deploy` CLI, `chumicro_workspace deploy` flat / `--import-graph` / `--boot-shim`, `pytest-device` staging, examples, functional tests).  Wrong-runtime adapter source no longer lands on a CP / MP board; PyPI sdists are unchanged.  Marker reader extracted to `chumicro_deploy._runtime_marker` so the bundle pipeline + every deploy walker share one implementation.  Filtering on by default at every orchestration boundary; transports own runtime via class identity; CLIs accept `--target-runtime <name>` as override.  AGENTS.md non-negotiable updated; Decision 0037 cross-references 0044.
- **Last shipped:** TBD on this commit.
- **In flight:** idle.
- **Blocked on:** —
- **Last touched:** AGENTS.md, plans/decisions/{0037,0044}-*, plans/next-up.md, scripts/bundle_manager.py, workbench/deploy/src/chumicro_deploy/{_runtime_marker,sources,flash_drive,circuitpython_transport,micropython_transport,cli}.py, workbench/deploy/tests/{test_runtime_marker,test_sources,test_flash_drive,test_circuitpython_transport,test_micropython_transport,test_cli}.py, workbench/workspace/src/chumicro_workspace/{deploy_source,import_graph,boot_shim,cli}.py, workbench/workspace/tests/{test_deploy_source,test_import_graph,test_boot_shim}.py.

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
