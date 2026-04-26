# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Pi Pico W flash-footprint cleanup pass — 800 KB CIRCUITPY drive + FAT12 4 KB clusters means every file costs ≥ 4 KB regardless of content; reducing file count is the dominant lever.
- **Last shipped:** Bundle pipeline strips `testing.py` from device deploys (saves ~24 KB across 6 libraries) + chumicro-mqtt consolidated 8 → 4 source files (3 deploy after testing.py exclusion); 139 mqtt tests pass at 94.37 % cov.
- **In flight:** Triaging pre-existing preflight failures from prior crashed agent session — griffe annotation warnings in `libraries/sockets` + `libraries/wifi` (docs gate) and 3 `workbench/workspace-template` tests expecting a `devices.yml` that Phase 4b intentionally removed from the template.
- **Blocked on:** —
- **Last touched:** `libraries/mqtt/src/chumicro_mqtt/{_wire,client,__init__}.py` (consolidation), `scripts/bundle_manager.py` + `scripts/tests/test_bundle_manager.py` (testing.py exclusion), `plans/learnings.md` (file-count vs FAT12 finding).

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
