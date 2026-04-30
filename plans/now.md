# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-repl audit landed — picking next workstream.**  Five-phase audit pass shipped as squash commit `2ff929d` (topic branch `audit/repl`).  **A:** device-side Tab completion — hardware-probed, `fetch_device_names` ships the friendly→raw→dir()→friendly round-trip in 8–45 ms across the four-board matrix, far below the perceptual instant threshold; `:rescan` invalidates after `import`.  **B:** workspace `python run.py repl` now picks line mode by default for TTY stdin (passthrough auto-fallback for non-TTY); `--mode {auto,line,passthrough}` flag for explicit override.  **C:** README + guide.md rewritten — drops the stale "side-portal feature set tracked separately" claim; `:command` table + two-source Tab-completion section added.  **D:** `run_loop` triple OSError-recovery branches deduped into one `_try_recover` closure.  **E:** new `coached_session_start(callable, *, output, prompt, max_attempts)` building block; `InteractiveReplSession` rewritten as thin wrapper; workspace `_cmd_repl` wraps `interactive_line` / `interactive` in coaching unless `--non-interactive`.  **F:** 9/9 repl functional tests + four-board live `fetch_device_names` verifier all green.  `chumicro-workspace` 0.0.1→0.0.2; chumicro-repl stays 0.0.0.  Workspace template repo's `AGENTS.md` updated separately (commit [`a625318`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/a625318)).  Workspace-ecosystem umbrella still closed; three carry-overs untouched.  Pi-Pico-W-CP-MQTT flash-mode-only routing and `--wipe` four-board hardware soak remain queued.
- **Last shipped:** chumicro-repl audit (5 phases / squash commit `2ff929d` / two-repo flow with template repo).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/repl/{README.md, docs/guide.md, src/chumicro_repl/{__init__,completion,line_mode,recovery,tui}.py, tests/test_{completion,line_mode,recovery}.py}`, `workbench/workspace/{VERSION, src/chumicro_workspace/cli.py, tests/test_cli.py}`, `plans/{now,next-up}.md`, template repo `AGENTS.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Pi-Pico-W-CP-MQTT flash-mode-only routing | `plans/next-up.md` (noted 2026-04-28) | Path forward identified: document the constraint and update `devices.yml` defaults / functional-test runner to auto-pick flash for that combination.  Small config-layer change; no runtime fix possible (CP parser needs ~14 KB heap to AST-build a single inline-bootstrap chunk of MQTT+sockets+wifi+harness; fundamental on 264 KB-SRAM Pi Pico W). |
| Hardware validation of `--wipe` | live boards | `--wipe` shipped behind unit tests + FakeTransport; the CP `storage.erase_filesystem()` reboot-and-reconnect dance and the MP recursive walk both want a one-time hardware soak across the four-board matrix before being declared production-ready.  `.scratch/clean_circuitpy_board.py` already exercises both runtime paths manually if a hand-driven check is preferred. |
| Carry-over: 3 deferred examples | template repo `examples/` | Hardware-network-stack examples (`periodic_get`, `telemetry_publisher`, `two_things`) were shipped in [`5ce73d4`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/5ce73d4); double-check them in `examples/README.md` and tweak if needed. |
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
