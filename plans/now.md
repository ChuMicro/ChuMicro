# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3a Slice 0 shipped — `chumicro-wifi` skeleton + `WifiConfig` + `WifiService` state machine + reconnect supervisor + `FakeWifi` testing helper + `_templates/config.toml` per ADR 0036 §5. Real adapters (CP, MP-ESP32, MP-RP2) stubbed for slices 1–3.
- **Last shipped:** Phase 3a Slice 0 — 40 host tests at 99.22 % cov, 16 functional tests pass across all 4 boards (Pi Pico W CP/MP, Lolin S2 CP/MP). One real-world finding lifted to learnings: CircuitPython RAM-mode silently bypasses module-level PEP 562 `__getattr__` (firmware supports it; the harness's class-as-module wrapper doesn't). Reverted wifi to Tier A eager package-level imports; per-function lazy adapter selection in `_select_adapter` (which works everywhere) keeps the actual benefit. Patterns + research docs amended.
- **In flight:** Phase 3a Slice 1 — CP `wifi.radio` adapter, hardware-verified on Lolin S2 CP + Pi Pico W CP.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
