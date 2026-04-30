# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **chumicro-msgpack audit follow-ups landed — chumicro-repl audit queued next.**  Audit was triggered by user noticing `chumicro_msgpack` imported from `workbench/workspace/tests/`, which violates the workbench-no-libraries boundary; same audit walked the wire-format subset story end-to-end.  Five workbench test imports flipped to PyPI `msgpack`; decoder error messages now name the offending tag (float64 / int64 / uint64 / `*32`-length) and point at the fix; byte-identity contract with `msgpack.packb(use_single_float=True)` pinned by a parametrised test in `libraries/msgpack/tests/test_msgpack_pytest.py`; README + module docstring rewritten to lead with "strict subset of standard MessagePack — bytes are spec-compliant" framing instead of "different from msgpack".  No 64-bit support added (intentional — keeps board-side decoder simple); stream API kept (already shipped, low cost).  Workspace-ecosystem umbrella remains closed as of 2026-04-29; three carry-overs tracked in `plans/next-up.md`.  User-confirmed cadence next: **chumicro-repl audit** (highest-readiness pickup), then Pi-Pico-W-CP-MQTT flash-mode-only routing, then `--wipe` four-board hardware soak.
- **Last shipped:** chumicro-msgpack audit follow-ups (workbench boundary fix, decoder error clarity, byte-identity contract test, README rewrite).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/msgpack/{README.md, src/chumicro_msgpack/{__init__,_pure}.py, tests/test_msgpack{,_pytest}.py}`, `workbench/workspace/{src/chumicro_workspace/writer.py, tests/test_*.py}`, `plans/{now,learnings}.md`.

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
