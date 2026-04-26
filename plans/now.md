# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Pi Pico W flash-footprint cleanup pass — Decision 0037 codified the per-runtime file-marking convention so the bundle pipeline can ship dedicated CP-mpy / MP-mpy bundles with non-applicable adapters + `testing.py` filtered out.
- **Last shipped:** Phase C — `__chumicro_runtimes__` markers on 9 runtime-specific files (wifi adapters, kvstore backends, sockets adapters), `bundle_manager._find_bundle_modules` filters by AST-read marker per `target_runtime`, `chumicro_wifi._adapters/fake.py` folded into `testing.py`, 6 new bundle tests + AGENTS.md non-negotiable updated.  Preflight green at 94 % cov.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/decisions/0037-runtime-file-marking.md` (new ADR), `scripts/bundle_manager.py` + `scripts/tests/test_bundle_manager.py` (filter + tests), `libraries/wifi/src/chumicro_wifi/{testing,service}.py` (fake fold + lazy import), `libraries/{wifi,kvstore,sockets}/src/.../*` (markers), `AGENTS.md` (non-negotiable + Decision 0037 link).

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
