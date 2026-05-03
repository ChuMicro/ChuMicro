# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-websockets — leanness pass underway** per `plans/workstreams/websockets-cleanup.md`.  v0.6.x ships 3,628 LOC deployed (vs chumicro-mqtt 1,842) — too fat for embedded targets.  Seven independent slices ranked smallest-blast-radius first: A (FrameParser per-byte→per-chunk), C (slim `__init__`), D (slim `CaseInsensitiveDict`), B (namespace classes→constants), F (compact docstrings + dead defensive code), E (merge handshake parsers), G (shared `_session.py`).  Each slice ships its own version bump + green preflight + commit.
- **Last shipped:** **chumicro-deploy hardening — rsync wedge root cause + prevention.**  Two compounding bugs found and fixed.  (1) `_stage_to_flash` and `deploy_files` did host-side drive operations (`.chu-probe` write, `boot_out.txt` read, `neuter_macos_metadata` sentinel plants) BEFORE sending the autoreload-off REPL command — so CP's filesystem watcher fired soft-reboots on each prep write, re-enumerating USB-CDC, leaving the board's USB stack degraded by the time rsync started.  Fixed by `_disable_autoreload_before_drive_writes()` helper called as the FIRST thing after `_enter_raw_repl()`; symmetric `_restore_autoreload()` consolidates the disconnect-side restore.  (2) Subprocess calls in `flash_drive.py` had no `timeout=` — once the kernel I/O wedged, rsync was unkillable.  Fixed with `RSYNC_TIMEOUT_SECONDS=90`/`SYNC_TIMEOUT_SECONDS=30`/`METADATA_HELPER_TIMEOUT_SECONDS=10`; `TimeoutExpired` converts to `FlashDriveError` with a board-reboot message.  Regression test snapshots wire-vs-filesystem ordering.
- **In flight:** idle.
- **Blocked on:** —
- **Last touched:** workbench/deploy/src/chumicro_deploy/circuitpython_transport.py, workbench/deploy/src/chumicro_deploy/flash_drive.py, workbench/deploy/tests/test_circuitpython_transport.py, workbench/deploy/tests/test_flash_drive.py, plans/learnings.md, plans/now.md.

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
