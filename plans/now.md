# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Idle — picking next workstream.**  Workspace-ecosystem umbrella (Phases 1, 2, 4, 5, 6, 7) closed 2026-04-27 — 6 of 7 phases shipped; only Phase 3 (per-environment deploys) deferred at user direction.  Multi-thing-staging-replacement also shipped end-to-end (`a7955fd`): transport primitive (`Deployer.deploy_diff` + `list_files_in_scope` + `delete_files`) plus workspace-CLI wiring so `python run.py deploy <thing>` and `repl <thing>` get scope cleanup by default.  Hardware-validated across all four runtime/board combos (CP flash + RAM, MP flash + RAM).  Only carry-over: a `--wipe` CLI flag for the corruption-recovery / clean-slate case.
- **Last shipped:** `a7955fd` — workspace CLI routes deploy + repl-with-thing through `Deployer.deploy_diff`.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/workspace/src/chumicro_workspace/cli.py`, `workbench/workspace/tests/test_cli.py`, `workbench/deploy/functional_tests/test_diff_deploy_hardware.py`, `plans/{now,next-up}.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| `--wipe` CLI flag | `chumicro-workspace deploy --wipe` | Last carry-over from multi-thing-staging-replacement.  Calls `storage.erase_filesystem()` (CP) / walk-and-delete (MP) before deploy.  Sketch in `plans/next-up.md`'s "Replace multi-thing staging…" entry.  Small slice; depends on the diff-deploy primitive that already shipped. |
| Phase 3 (per-env deploys) | `plans/workstreams/workspace-ecosystem.md` §Phase 3 | Deferred at user direction during Phase 4.  ~250 LOC sketched in the umbrella plan: workspace.yml `environments:` block, `deploy --env <name>`, `use <env>` to set the active env in `~/.chumicro/<workspace>/active-env`. |
| Carry-over: 3 deferred examples | template repo `examples/` | Hardware-network-stack examples (`periodic_get`, `telemetry_publisher`, `two_things`) were shipped in [`5ce73d4`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/5ce73d4); double-check them in `examples/README.md` and tweak if needed. |
| Carry-over: Phase 5 `agent_strictness` | `chumicro_workspace.quality` | Field accepted today, AST-level enforcement (no naked `except:`, no global state in things) deferred.  Own design pass. |
| Carry-over: Phase 7 device-side completer | `chumicro_repl.completion.DeviceCompleter` | Architecture shipped; the on-wire `dir()` query is a follow-on once friendly-↔-raw REPL mode-switching has a clean design. |
| Carry-over: Phase 2f mapping config | umbrella §Phase 2f | Per-thing → per-device mapping configuration (deploy this thing to that device by default).  `--all-devices` covered the common case. |
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
