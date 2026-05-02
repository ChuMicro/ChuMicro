# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace-ecosystem Phase 2f closed.**  Per-thing → per-device mapping landed end-to-end across both repos.  New `workspace.yml` `deploy_targets:` block + `chumicro_workspace.deploy_targets.read_deploy_targets` parser; `_cmd_deploy` extracted into `_build_deploy_plan` returning `[(thing, dir, [Device])]` so the deploy loop is uniform across single-thing / `--all-devices` / `--all-things`.  Two flows: (1) bare `deploy <thing>` without `--device` consults `deploy_targets[thing]` first, falls back to `devices.yml` defaults; (2) new `--all-things` flag walks the whole mapping in declaration order.  Mono-repo commit `ec1d133` (`chumicro-workspace` 0.0.2 → 0.0.3); template-repo commit [`4607864`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/4607864) (workspace.yml docs + AGENTS.md row).  24 new unit tests; 100 % coverage on the new module; preflight green at the agent 94 % gate.  Today's earlier work: examples audit (template-repo `e8854fe`) + CP wipe→ready FAT-remount poll (mono-repo `1454c45`, chumicro-deploy 0.4.3).  One carry-over left in the workspace-ecosystem queue: Phase 5 `agent_strictness` AST checks.
- **Last shipped:** mono-repo `ec1d133` (chumicro-workspace 0.0.3 — Phase 2f); template-repo `4607864` (workspace.yml docs).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/workspace/{VERSION, README.md, docs/guide.md, src/chumicro_workspace/{__init__,cli,deploy_targets}.py, tests/{test_cli,test_deploy_targets}.py}`; template repo `{workspace.yml, AGENTS.md}`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
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
