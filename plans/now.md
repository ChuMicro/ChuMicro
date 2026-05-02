# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace-ecosystem umbrella now genuinely closed.**  Two slices today.  (1) Phase 2f shipped per-thing `deploy_targets:` mapping + `deploy --all-things` end-to-end (mono-repo `ec1d133`, chumicro-workspace 0.0.2 → 0.0.3; template-repo [`4607864`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/4607864)).  (2) The remaining "Phase 5 carry-over: `agent_strictness` AST checks" was dropped per the no-speculative-public-API rule — the `quality.agent_strictness` field had no consumer since 2026-04-27 and the AST-check design pass was never done; removed rather than left as decorative config surface (consumer-less code rots quietly).  Today's earlier work: examples audit (template-repo `e8854fe`) + CP wipe→ready FAT-remount poll (mono-repo `1454c45`, chumicro-deploy 0.4.3).  No workspace-ecosystem carry-overs remain.
- **Last shipped:** chumicro-workspace 0.0.4 (agent_strictness removal pending) + 0.0.3 (Phase 2f).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/workspace/{VERSION, src/chumicro_workspace/quality.py, tests/test_quality.py, docs/guide.md}`; `plans/workstreams/{workspace-ecosystem,project-workspace}.md`; template repo `workspace.yml`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
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
