# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **`testing.py` exits every bundle and every device deploy.**  User noticed `testing.py` files riding along to the board on workspace-template deploys.  Investigation surfaced a four-list drift: `bundle_manager._HOST_ONLY_MODULES` filtered `testing.py` from circup/mip but `DirectorySource`, MP `_copy_tree` flash staging, and CP `flash_drive.rsync` did not.  Bundles also shipped `testing.py` in the universal source bundle (`mip install` from the bundle root would land it on a device).  Fix: every `testing.py` declares `__chumicro_runtimes__ = ("cpython",)`; `file_targets_runtime` accepts a frozenset target; bundle pipeline's universal source bundle now passes `DEVICE_RUNTIMES = frozenset({"circuitpython", "micropython"})`, dropping cpython-only marked files.  `_HOST_ONLY_MODULES` retired — the marker is the single source of truth.  PyPI sdist + wheel still ship every file unfiltered (every adapter, every fake) — `pip install chumicro-foo` on CPython hosts gets the complete library.  Decision 0037 amended (2026-05-04 §"Amendments"); 0044 cross-references updated; AGENTS.md tightened.
- **Last shipped:** `chumicro: testing.py and cpython-only files exit every bundle and every device deploy via __chumicro_runtimes__ marker (Decision 0037 amendment)` (this commit).  Earlier today: `7720e46` (chumicro-workspace install-libraries CLI, gap 4), `48ac7e3` (add_device default-slot fix, gap 6), `e358442` (README hero pass 2).
- **In flight:** idle.
- **Blocked on:** —.
- **Last touched:** Decision 0037, Decision 0044, AGENTS.md, `bundle_manager.py`, `runtime_marker.py`, every `libraries/*/src/chumicro_*/testing.py`, scaffold template.

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
