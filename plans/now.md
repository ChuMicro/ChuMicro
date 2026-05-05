# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Promoted on-device-config-dogfooding to peer workstream.  Renamed `phase-4-5b-on-device-config-dogfooding.md` → `on-device-config-dogfooding.md`, applied audit-driven edits (corrected exception list to `(OSError, InvalidConfigType)`, struck stale `secrets.yml` premise per Decision 0057, sequenced plugin wiring + first consumer + hardware validation as Step 1, added `NOW_UTC_TUPLE` to Step 2 scope, added VERSION-bump + conftest-sweep to Step 4 / pre-conditions).  Cross-references in Decisions 0055/0056, parent workstream, and `next-up.md` updated.
- **Last shipped:** `Restore Decision 0056 + surface ADR conventions in AGENTS.md` (commit `7892f52`).
- **In flight:** idle — the on-device-config-dogfooding workstream is now ready to pick up cold; needs hardware-in-the-loop session.  Side-task chip open: fix `new-decision` skill's drift with `plans/decisions/README.md`.
- **Blocked on:** —.
- **Last touched:** `plans/workstreams/on-device-config-dogfooding.md` (renamed + rewritten), `plans/workstreams/scripts-workbench-config-unification.md`, `plans/decisions/0055-config-pipeline-unification.md`, `plans/decisions/0056-transport-extra-files-staging.md`, `plans/next-up.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| On-device config dogfooding (was Phase 4.5b) | `plans/workstreams/on-device-config-dogfooding.md` | Plan validated + edited; ready to pick up cold.  Step 1 = plugin hook design + wifi as first consumer + 4-board hardware validation; Steps 2-4 mechanical. |
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
