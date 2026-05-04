# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Streaming output + status modes for parallel tasks** ([Decision 0054](decisions/0054-streaming-output-and-status-modes.md)).  Replaced `subprocess.run(capture_output=True)` with `shared.stream_subprocess` (`Popen` + line-reader); built `_Sink` / `_Dispatcher` abstraction with quiet / interleave / status modes (TTY auto-detect; `--quiet` flag); collapsed `_run_phases_in_parallel` + `_run_capture_phases_in_parallel` into one helper; auto-sized `phase_workers` / `package_workers` from `cpu_count()` with product cap.  Decision 0048 §3 + §5 + §6 edited in place to reflect the new shape.
- **Last shipped:** `scripts/{run,shared}: streaming output + status modes for parallel tasks (Decision 0054)` (commit `67cda99`).
- **In flight:** idle — back to ADR audit phases 3–4 (compact length offenders, write missing high-level ADRs), or pick up something fresh from `## Next` of `plans/next-up.md`.
- **Blocked on:** —.
- **Last touched:** `scripts/run.py`, `scripts/shared.py`, `scripts/tests/test_{run,shared}.py`, `plans/decisions/0054-streaming-output-and-status-modes.md`, `plans/decisions/0048-preflight-phase-level-parallel.md`.

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
