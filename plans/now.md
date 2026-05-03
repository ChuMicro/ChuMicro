# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Cross-runtime test recovery — done.**  Audit at session start showed 24 silently-SKIPped test files holding ~889 test functions never actually exercised on MicroPython / CircuitPython unix-ports.  Decision 0016 was already in place but the harness's silent-SKIP-on-ImportError fallback was letting mis-classified files quietly disappear.  Now: 1147 cross-runtime tests passing on each unix-port (vs 365 baseline), zero SKIPs, zero contract-violating files.  Harness now FAILs hard on ImportError for non-`_pytest` files.
- **Last shipped:** **`test_harness`: ImportError on a non-`_pytest` test file is now a hard FAIL** (commit `3e392df`).  Closes the loop: the contract is now self-enforcing — either a file is converted to cross-runtime or it carries a `_pytest` suffix.  Sequence of commits this session: `8bd7f14` (harness `raises(match=)` + deque fix + ntp conversion), `bcc3219` (events/mqtt/sockets/http_server/requests + harness class discovery + 4 source bugs), `e8fc3ec` (websockets source fixes), `73f317e` (CP unix-port SSL+axtls + websockets test conversion), `ceb5ca4` (rename CPython-only files to `_pytest`), `4d31b6a` (clear last 7 SKIPs — convert what's convertible, rename what's genuinely CPython-only), `3e392df` (harness FAIL-on-ImportError tightening).
- **In flight:** idle.
- **Blocked on:** —.
- **Last touched:** scripts/prepare_circuitpython.py, support/test_harness/{src,tests}, libraries/{events,http_server,logging,mqtt,ntp,requests,sockets,websockets}/{src,tests}, plans/{next-up,learnings,now}.md.

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
