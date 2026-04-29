# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Idle — picking next workstream.**  Multi-thing-staging-replacement workstream now fully closed: `--wipe` CLI flag shipped end-to-end (`Deployer.deploy_diff(wipe=True)` + `TransportProtocol.wipe_filesystem()` on CP / MP / FakeTransport + `chumicro-workspace deploy --wipe`).  Ordinary deploys clean stale `/lib/*` via the diff primitive shipped 2026-04-27; `--wipe` covers the corruption-recovery / clean-slate case where the user wants the whole user filesystem gone (CP `storage.erase_filesystem()`, MP recursive walk-and-delete).  RAM-mode no-ops silently inside the transport.  Workspace-ecosystem umbrella: **closed** as of 2026-04-29 (Phase 3 per-environment deploys dropped — speculative dev/staging/prod seam, no concrete consumer).  Three independent carry-overs (Phase 2f mapping config / Phase 5 `agent_strictness` checks / Phase 7 device-side completer) tracked in `plans/next-up.md` for if-and-when triggers appear.
- **Last shipped:** workspace + chumicro-deploy: `--wipe` flag for corruption-recovery / clean-slate deploys.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/deploy/src/chumicro_deploy/{protocol,deployer,circuitpython_transport,micropython_transport,testing}.py`, `workbench/deploy/tests/test_{circuitpython,micropython}_transport.py`, `workbench/deploy/tests/test_diff_deploy.py`, `workbench/workspace/src/chumicro_workspace/cli.py`, `workbench/workspace/tests/test_cli.py`, `workbench/workspace/{README.md,docs/guide.md}`, `workbench/{deploy,workspace}/VERSION`, `plans/{now,next-up}.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Hardware validation of `--wipe` | live boards | `--wipe` shipped behind unit tests + FakeTransport; the CP `storage.erase_filesystem()` reboot-and-reconnect dance and the MP recursive walk both want a one-time hardware soak across the four-board matrix before being declared production-ready.  `.scratch/clean_circuitpy_board.py` already exercises both runtime paths manually if a hand-driven check is preferred. |
| `chumicro-repl` audit pass | `plans/next-up.md` (queued 2026-04-29) | Same audit playbook the deploy + workspace passes followed.  User-flagged: docs lag behind recent updates; code quality / surface coherence unclear.  Smaller-surface package than deploy / workspace; likely 3–5 commits to land. |
| Carry-over: 3 deferred examples | template repo `examples/` | Hardware-network-stack examples (`periodic_get`, `telemetry_publisher`, `two_things`) were shipped in [`5ce73d4`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/5ce73d4); double-check them in `examples/README.md` and tweak if needed. |
| Carry-over: Phase 2f mapping config | umbrella §Phase 2f | Per-thing → per-device mapping config (deploy this thing to that device by default).  `--all-devices` covered the common case.  Trigger: a user with multiple boards starts feeling the per-deploy `--device` typing.  ~50–100 LOC. |
| Carry-over: Phase 5 `agent_strictness` | `chumicro_workspace.quality` | Field accepted today, AST-level enforcement (no naked `except:`, no module-level mutable state in things) deferred.  Trigger: agent-authored thing code starts surfacing the sloppiness the strictness ratchet was meant to catch.  Own design pass — likely 5–10 checks to settle. |
| Carry-over: Phase 7 device-side completer | `chumicro_repl.completion.DeviceCompleter` | Architecture shipped; the on-wire `dir()` query is a follow-on once friendly-↔-raw REPL mode-switching has a clean design.  Today: REPL tabs against keywords + builtins only; device-defined symbols don't autocomplete. |
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
