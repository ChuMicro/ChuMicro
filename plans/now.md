# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **MP transport idle-timeout follow-up — done.**  CP transport's `_EXECUTE_IDLE_TIMEOUT = 60.0` (commit `ecf002c`) closed the silent-bootstrap timeout for CP, but the MP transport hadn't been touched.  On Lolin S2 MP (2 MB heap), the on-device fragmentation tests' histogram bisection blew past the existing `timeout=120` and surfaced as `TransportError: timeout waiting for first EOF reception` from mpremote's `follow()`.  Bumped MP's test-bootstrap path to `_EXECUTE_IDLE_TIMEOUT = 300.0` (proportional to MP's bigger heap) and verified on hardware: every fragmentation test in requests/http_server/websockets now RUNs to completion (180–261 s each); the remaining failures are pre-existing library-side fragmentation/leak metrics, not transport timeouts.
- **Last shipped:** `chumicro-deploy: MP transport idle-timeout for silent-bootstrap path` (this commit).  Mirrors the CP fix from `ecf002c` for the MicroPython side.  Lifted: learning about `mpremote.exec_raw(timeout=N)` semantics into `plans/learnings.md` §MicroPython runtime quirks.
- **In flight:** idle.
- **Blocked on:** —.
- **Last touched:** workbench/deploy/{src/chumicro_deploy/micropython_transport.py, tests/test_micropython_transport.py}, plans/{learnings,now}.md.

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
