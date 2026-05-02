# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Per-runtime adapter-selection helper plan dropped.**  Latest in a small string of "kill speculative scaffolding" cleanups (alongside `agent_strictness` field removal and library-self-declared deploy-mode constraints abandonment, both this week).  Original plan was to extract a `chumicro_compat.runtime.select_for_runtime({...})` helper to dedupe the `sys.implementation.name` ladder shared by `chumicro_wifi.service._select_adapter` and `chumicro_kvstore.core._select_backend`.  Two reasons it's dead: (1) the wifi unification (commit `0304542`) already collapsed wifi's ladder to 3-way by moving substrate-aware logic *inside* the adapter — only kvstore's ladder remains, so no DRY case for a helper.  (2) Kvstore's backends aren't slight API variants the way the wifi adapters were; they're fundamentally different storage technologies (CP NVM raw bytes / MP NVS k/v dict / MP LittleFS files / CPython memory).  Nothing to extract.  20-line dispatch ladder in `_select_backend` is the right shape.
- **Last shipped:** plan-cleanup: drop per-runtime adapter helper plan (this commit).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/next-up.md` (entry removed + Done-section pointer added).

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
