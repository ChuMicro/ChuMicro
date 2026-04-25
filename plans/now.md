# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3b closed + config conventions pinned via Decisions 0035 (file structure) + 0036 (`chumicro-config` library). Next: Phase 3a (`chumicro-wifi`) consumes `chumicro-config` for its `WifiConfig.from_dict`.
- **Last shipped:** `chumicro-config` library + Decision 0036 — standardized `load_section` factory that every consumer library's `from_dict` calls, plus `load_runtime_config` reader for `/runtime_config.msgpack`. 19 host tests at 100 % cov; cross-runtime clean. ADR 0035 §3 amended to point at the new library.
- **In flight:** Phase 3a Slice 0 — `chumicro-wifi` scaffold + `WifiConfig` using `chumicro_config.load_section`.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
