# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-websockets — leanness pass underway** per `plans/workstreams/websockets-cleanup.md`.  v0.6.x ships 3,628 LOC deployed (vs chumicro-mqtt 1,842) — too fat for embedded targets.  Seven independent slices ranked smallest-blast-radius first: A (FrameParser per-byte→per-chunk), C (slim `__init__`), D (slim `CaseInsensitiveDict`), B (namespace classes→constants), F (compact docstrings + dead defensive code), E (merge handshake parsers), G (shared `_session.py`).  Each slice ships its own version bump + green preflight + commit.
- **Last shipped:** **chumicro-deploy unification + size-based timeouts + FAT-cache refresh.**  (1) Extracted `_push_staging_to_drive` shared helper — both `_stage_to_flash` (functional tests) and `deploy_files` (production deploy) now share the host-side drive-write phase (enter raw REPL → disable autoreload → resolve drive → plant sentinels → rsync → cleanup → flush).  (2) Replaced fixed 90s rsync timeout with size-based formula: `timeout = max(MIN, BASE + size_mb × PER_MB)` defaulting to 240s floor / 120s base / 600s per MB.  Lolin S2 was hitting the 90s false-positive even when the rsync was just genuinely slow.  (3) Added `_refresh_board_fat_cache_after_rsync` for `_stage_to_flash` — back-to-back stages were failing with `ImportError: no module named X.Y` because CP's in-RAM FAT cache was stale; the old prep flow inadvertently invalidated it via autoreload firing on pre-rsync sentinel writes (which we removed).  Bake-validated against Pi Pico W + Lolin S2 in flash mode, back-to-back: 8/8 + 8/8 + 7/8 (the only failure is a pre-existing test-side EADDRINUSE on a fixed-port socket — needs SO_REUSEADDR).  737 deploy tests pass.
- **In flight:** idle.
- **Blocked on:** Preflight blocked by 3 untracked files from a prior session (`libraries/http_server/tests/test_memory_fragmentation.py`, `libraries/requests/tests/test_memory_fragmentation.py`, `libraries/requests/tests/test_memory_pressure.py`) — these were created by another agent before this session started, are not in git, and have CP-incompatible code (e.g., `hashlib.new` calls).  Need user direction on whether to delete, fix, or leave.
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
