# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Project-workspace Phase 3b in flight — `chumicro-kvstore` Slices 0–2 landed 2026-04-25 (Decision 0034 + scaffold + MemoryBackend + CP NVM with CRC framing, hardware-verified on both CP boards). Next: Slice 3 (MP NVS on Lolin S2 MP).
- **Last shipped:** Phase 3b Slice 2 — CP NVM backend with full `MAGIC | LEN | CRC32 | MSGPACK` framing, hardware-verified on Pi Pico W (4 KB NVM) and Lolin S2 (8 KB NVM); 64 host tests at 99.7 % cov; 8 functional tests passing on each CP board.
- **In flight:** Phase 3b Slice 3 (MP NVS backend on Lolin S2 MP, namespace `chu_kv`).
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
