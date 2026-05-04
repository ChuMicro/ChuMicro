# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **README hero pass 2 — un-bury the matrix.**  User pushed back on the "Eight lines, no freeze" landing page that shipped in `d230676` and the SMIL-animated SVG that landed in `abdf6e4`: "marketing mumbo jumbo," "the entire top page is meaningless," "users dont know what runners are when they land on this repo," and "library matrix is hidden behind a tiny `[Libraries](libraries/)` link."  Pendulum had also swung the other way on async — the rude rule-shape "no async, no threads, no ISRs" was reframed away in Phase 1, leaving zero mention of async at all.  Fix: replaced the hero with a concrete one-liner ("Keep a status LED blinking, even through a slow network call"), restored the 15-row library matrix + 4-row workbench matrix back onto the root README, kept `INSTALL.md` split, deleted `support/docs/heartbeat-vs-sleep.svg`, dropped the stray `# no threads, no async` comment from `mqtt/README.md:42`.  Async now mentioned once neutrally ("No async/await, no threads") with the genuine cross-runtime reason — not as a rule.
- **Last shipped:** `README + libraries/mqtt/README.md + support/docs: rewrite README hero, restore library + workbench matrices, drop heartbeat-vs-sleep SVG` (this commit).  Earlier today: `abdf6e4` (heartbeat-vs-sleep SVG + mqtt/wifi docs landings — *now reverted in part*), `48ba00a` (Tier 1 audit follow-ups), `49fb45e` (CHUMICRO_PARALLEL_* env vars dropped for flags).
- **In flight:** idle.  Note: there's pre-existing uncommitted WIP from a parallel session on `chumicro_workspace.boot_shim`; not mine, left alone.
- **Blocked on:** —.
- **Last touched:** `README.md`, `libraries/mqtt/README.md`, `support/docs/heartbeat-vs-sleep.svg` (deleted), `plans/now.md`, `plans/next-up.md`.

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
