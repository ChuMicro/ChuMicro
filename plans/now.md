# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **CP wipe → ready path is now data-validated end-to-end.**  4/4 boards pass `.scratch/wipe_soak.py`.  The two follow-ups queued from the 2026-04-30 soak (multi-CIRCUITPY-drive shuffle, Lolin S2 CP needing manual reset) both turned out to be wrong hypotheses for the same underlying bug — a host-side timing race after `storage.erase_filesystem()`: USB-CDC and the FAT volume re-enumerate on independent macOS timelines (CDC first, FAT typically a few seconds later, plus a brief mount-not-yet-writable EACCES window after that).  `wipe_filesystem()` waited only for CDC, so an immediate post-wipe `deploy_files` raced both phases.  Fix: new `_wait_for_circuitpy_remount()` helper polls `_resolve_circuitpy_drive` (already exercises `is_dir` + probe write/unlink) until it returns cleanly or a 10 s `_WIPE_FAT_REMOUNT_TIMEOUT_SECONDS` budget exhausts.  Lolin S2 CP wipe→ready 17.99 s, Pi Pico W CP 9.49 s, both MP under 100 ms.  Five new unit tests.  Workspace-ecosystem umbrella still closed; three carry-overs untouched.
- **Last shipped:** chumicro-deploy 0.4.3 (FAT remount poll).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/deploy/{VERSION, src/chumicro_deploy/circuitpython_transport.py, tests/test_circuitpython_transport.py}`, `plans/{now,next-up}.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Carry-over: 3 deferred examples | template repo `examples/` | Hardware-network-stack examples (`periodic_get`, `telemetry_publisher`, `two_things`) were shipped in [`5ce73d4`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/5ce73d4); double-check them in `examples/README.md` and tweak if needed. |
| Carry-over: Phase 2f mapping config | umbrella §Phase 2f | Per-thing → per-device mapping config (deploy this thing to that device by default).  `--all-devices` covered the common case.  Trigger: a user with multiple boards starts feeling the per-deploy `--device` typing.  ~50–100 LOC. |
| Carry-over: Phase 5 `agent_strictness` | `chumicro_workspace.quality` | Field accepted today, AST-level enforcement (no naked `except:`, no module-level mutable state in things) deferred.  Trigger: agent-authored thing code starts surfacing the sloppiness the strictness ratchet was meant to catch.  Own design pass — likely 5–10 checks to settle. |
| Anything else in `## Now` of `next-up.md` | `plans/next-up.md` | Rebrand to ChipPy, OTA workstream (`plans/workstreams/ota.md`), shared per-runtime adapter helper, performance benchmarking infrastructure, etc. |

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
