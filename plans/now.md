# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **scripts/workbench audit — Python-in-Python and env-var-as-arg pushback (1c, 2a).**  User flagged two patterns they don't like across `scripts/` + `workbench/`: Python invoking Python (kept where reasonable — `python -m <tool>` for griffe / pytest / build / ruff / coverage / zensical / pip; the `run.py` → `run.py` self-respawn for preflight phase capture stays per Decision 0048 since the alternative is a 200-300 line writer-threading refactor across 8 files for marginal gain) and env-var-as-arg (dropped where flags are equivalent — `CHUMICRO_PARALLEL_PACKAGES` / `CHUMICRO_PARALLEL_PREFLIGHT_PHASES` replaced with `--package-workers` / `--phase-workers` / `--max-workers` flags on `preflight`, `build`, `docs`, `test`, and `check-api`; `CHUMICRO_DEVICES` left alone since CI is the documented consumer).  Also dropped the `.venv/bin/python` lookup in `audit_gates.py` — `sys.executable` is already the right interpreter.  Decision 0048 §5 + `plans/next-up.md` Done entry updated to match.
- **Last shipped:** `scripts: drop CHUMICRO_PARALLEL_* env vars and .venv lookup; flags-only` (this commit).
- **In flight:** idle.
- **Blocked on:** —.
- **Last touched:** `scripts/{run.py,check_api.py,audit_gates.py}`, `scripts/tests/test_run.py`, `plans/decisions/0048-preflight-phase-level-parallel.md`, `plans/next-up.md`, `plans/now.md`.

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
