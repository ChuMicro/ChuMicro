# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Routine consolidation slice on `chumicro-wifi`.**  Unified `MpEsp32WifiAdapter` + `MpRp2WifiAdapter` into a single substrate-aware `MpWifiAdapter` (`_adapters/mp.py`) with `stack="espidf" | "cyw43"` parameterisation.  The two classes shared ~80 % of their bodies; the actual differentiator is which `wlan.config(**kwargs)` knob is applied (ESP-IDF: `reconnects=0` post-first-connect; CYW43: `pm=0xa11140` at configure time).  `WifiService._select_adapter` collapsed from 4-way to 3-way (CP / MP / fake), matching the shape `chumicro-sockets` already uses.  Dead `NAMESPACE = "esp32"` class attribute (zero readers) dropped along the way.  88 unit tests green at 100 % coverage on the new module; 98.88 % library-wide.  `chumicro-wifi` 0.0.2 → 0.0.3.
- **Last shipped:** chumicro-wifi 0.0.3 — MP adapter unification (commit `0304542`).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/wifi/{VERSION, README.md, src/chumicro_wifi/{service.py, _adapters/mp.py}, tests/{test_wifi.py, test_mp_adapter.py}, functional_tests/test_mp_adapter_on_device.py}`; `plans/learnings.md` (new MP-WLAN-substrate-identity entry).

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Hardware soak the unified MP adapter | four-board matrix | `python scripts/run.py test-libraries-functional --library wifi --runtime micropython` — confirms zero behavioural drift on real ESP-IDF + CYW43 boards.  Logic is byte-identical to the split classes, so low risk; can ship without it but cleaner to verify. |
| Extract shared per-runtime adapter helper | `next-up.md` `## Next` | Now has only **one** remaining ladder consumer (`chumicro_kvstore.core._select_backend`); the wifi unification removed the second.  Even less urgent than before — the next-up entry's "low urgency until a third consumer surfaces" caveat applies more strongly now. |
| Anything else in `## Now` of `next-up.md` | `plans/next-up.md` | Rebrand to ChipPy, OTA workstream (`plans/workstreams/ota.md`), performance benchmarking infrastructure, etc. |

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
