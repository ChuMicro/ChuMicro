# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Project-workspace Phase 3b in flight — `chumicro-kvstore` Slices 0–3 landed 2026-04-25 (Decision 0034 + scaffold + MemoryBackend + CP NVM with CRC framing + MP NVS single-payload-blob, all hardware-verified). Next: Slice 4 (MP LittleFS on Pi Pico W MP).
- **Last shipped:** Phase 3b Slice 3 — MP NVS backend (single payload blob under fixed key in `chu_kv` namespace; ADR §6 pivoted from per-dict-key to single-blob since MP's `esp32.NVS` doesn't expose key enumeration). 78 host tests at 99.7 % cov; 6 functional tests passing on Lolin S2 MP.
- **In flight:** Phase 3b Slice 4 (MP LittleFS backend on Pi Pico W MP — single `/_chu_kv.msgpack` with tmpfile + rename atomicity).
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
