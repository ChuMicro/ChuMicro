# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** ADR / skill bookkeeping fix.  Restored Decision 0056 (deleted as collateral in commit `6ab0a40`'s 4→2-layer cleanup; the implementation it documents is shipped and live).  AGENTS.md now points at `plans/decisions/README.md` + inlines the load-bearing rules (edit-in-place, four-value status enum, no banner blockquotes / `## Update` sections / `Revised:` lines).
- **Last shipped:** `Restore Decision 0056 + surface ADR conventions in AGENTS.md`.
- **In flight:** Phase 4.5b plan validation surfaced concrete edits (stale `secrets.yml` premise, exception list off-by-one, plugin wiring not yet implemented, `NOW_UTC_TUPLE` in scope, missing device-side `extra_files` round-trip functional test, `chumicro-pytest-device` VERSION bump).  Pending user confirmation on whether to apply them, and on whether plugin-side `extra_files` wiring should be split out as foundation pre-work or kept inside 4.5b's scope.  Side-task chip open: fix `new-decision` skill's drift with `plans/decisions/README.md`.
- **Blocked on:** —.
- **Last touched:** `plans/decisions/0056-transport-extra-files-staging.md`, `AGENTS.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Phase 4.5b plan edits + scope decision | `plans/workstreams/phase-4-5b-on-device-config-dogfooding.md` | Audit findings ready to apply; open question: split plugin-wiring out as foundation or keep inside 4.5b. |
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
