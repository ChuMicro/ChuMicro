# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Project-workspace Phase 3b in flight — `chumicro-kvstore` Slice 0 (Decision 0034) + Slice 1 (scaffold + MemoryBackend + FakeKVStore + 43 host tests at 99.6 % cov) landed 2026-04-25. Next: Slices 2–4 (CP NVM, MP NVS, MP LittleFS) on plugged-in hardware.
- **Last shipped:** Phase 3b Slices 0+1 — Decision 0034 nails down the API + per-backend contracts; `libraries/kvstore/` ships the `KVStore` class, exception hierarchy, MemoryBackend, FakeKVStore, and pyproject wired to depend on `chumicro-msgpack`.
- **In flight:** Phase 3b Slice 2 (CP NVM backend on Lolin S2 + Pi Pico W CP).
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
