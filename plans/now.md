# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace template examples audit closed.**  Reviewed all five non-trivial examples in [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) `examples/` against the canonical `things/example_sensor/app.py` reference; surfaced two real bugs that ruff + the existing parametrized `test_workspace.py` couldn't catch.  (1) `wifi_only/app.py:50` printed `self._wifi.state.value` — `WifiState.CONNECTED = "connected"` is a plain string, so `.value` access AttributeErrors the first non-CONNECTED tick.  (2) Five `is` / `is not` comparisons across the four newer examples (`periodic_get`, `telemetry_publisher` ×2, `two_things` sensor + server, `wifi_only`) — string-typed state constants only "work" with identity-comparison via Python's small-string interning, deviates from both the chumicro-wifi state docstring's documented pattern and the canonical reference.  Both fixed in template-repo commit [`e8854fe`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/e8854fe).  All five examples import-smoke clean under chumicro-dev mode; ruff + pytest 3/3 green.  Earlier (today) the CP wipe→ready path landed end-to-end at 4/4 on the soak (commit `1454c45` in mono-repo; chumicro-deploy 0.4.3).  Workspace-ecosystem umbrella still closed; two carry-overs remain (Phase 2f mapping config, Phase 5 `agent_strictness`).
- **Last shipped:** template-repo `e8854fe` (examples bug-fix); mono-repo chumicro-deploy 0.4.3 (FAT remount poll).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** template repo `examples/{wifi_only,periodic_get,telemetry_publisher,two_things/{sensor,server}}/app.py`; mono-repo `plans/{now,next-up}.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
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
