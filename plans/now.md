# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **CP-wipe-reconnect fix + RAM-too-heavy constraint relocated to the right layers — picking next workstream.**  Three commits today.  `9da3680` rewrites the post-`storage.erase_filesystem()` reconnect from "5 s sleep + one-shot connect" to "2 s seed + 30 s polling reconnect" — surfaced by `.scratch/wipe_soak.py` measuring 8.10 s on a populated Pi Pico W CP.  Hardware soak result: 2/4 boards (both MP) clean; Pi Pico W CP recovered the wipe call but tripped on a separate multi-CIRCUITPY-drive corner case; Lolin S2 CP appeared to need a manual reset.  `f225fe5` initially added a `(library, runtime, board-fingerprint)` constraint table to `chumicro-pytest-device` for the MQTT-on-Pi-Pico-W-CP routing — user pushback was right that it inverted the dependency direction (generic test tool shouldn't carry library × board × runtime knowledge) and only covered the test path while leaving the workspace deploy path bare; reverted in `95e57fc`, replaced in `9740f15` with the right minimal pieces: clearer `INSUFFICIENT_MEMORY` recovery plan in `chumicro-deploy` (calls out both `chumicro-deploy --deploy-mode flash` AND `chumicro-workspace` `devices.yml` `deploy_mode: flash` paths), plus a "Heads-up for small-RAM CircuitPython boards" block in `libraries/mqtt/README.md`.  Library-self-declared `[tool.chumicro]` constraints queued for when a second library hits the wall (one data point isn't enough to design a schema).  Workspace-ecosystem umbrella still closed; three carry-overs untouched.
- **Last shipped:** chumicro-deploy 0.4.2 (recovery-plan rewrite) + libraries/mqtt/README.md heads-up block.
- **In flight:** —
- **Blocked on:** —  Lolin S2 CP needs a manual reset before any further wipe-soak attempts against it.
- **Last touched:** `workbench/deploy/{VERSION, src/chumicro_deploy/{circuitpython_transport,recovery}.py}`, `libraries/mqtt/README.md`, `plans/{now,next-up}.md`.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Multi-CIRCUITPY-drive volume-name shuffle on wipe | `plans/next-up.md` (noted 2026-04-30) | After `storage.erase_filesystem()` reformats one of two simultaneously-mounted CP drives, the OS can swap which board gets the bare `/Volumes/CIRCUITPY` vs `/Volumes/CIRCUITPY 1` suffix — the transport's cached `circuitpy_drive_path` is then stale.  Fix sketch: re-resolve the drive after the reboot via the existing `find_circuitpy_drive_for_uid()` / `find_circuitpy_drive_for_machine()` helpers so the match is content-based.  Today's workaround: don't run wipe with multiple CP boards plugged in. |
| Lolin S2 CP wipe + manual reset investigation | `plans/next-up.md` (noted 2026-04-30) | The Lolin S2 CP didn't come back over USB-CDC after `storage.erase_filesystem()` during the four-board soak; needed a manual reset to recover.  Pi Pico W CP under the same flow recovered fine.  Worth investigating whether it's CP safe-mode landing or a USB-stack hang specific to the S2 chip / firmware combination — but only after a fresh manual reset and a controlled reproducer. |
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
