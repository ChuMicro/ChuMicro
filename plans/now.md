# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3a Slice 1 shipped — CP `wifi.radio` adapter live on Lolin S2 CP + Pi Pico W CP. Real MP adapters (ESP32, Pi Pico W CYW43) stubbed for Slices 2–3.
- **Last shipped:** Phase 3a Slice 1 — `CpWifiAdapter` wraps the CP `wifi.radio` singleton with constructor injection (tests use a `_FakeRadio`, production uses the real one). 53 host tests at 99 % cov; 10 functional tests pass on each CP board (4 lazy-load sanity + 6 adapter contract incl. timeout-against-non-existent-AP). Substrate failure path catches `OSError` (parent of CP's `TimeoutError` / `ConnectionError` — narrower subclasses aren't builtins on MP, and the source has to load on every runtime). Sub-fix: scaffolder's Tier B comment updated to recommend per-function selectors instead of module-level PEP 562 (after the Slice 0 CP RAM-mode finding).
- **In flight:** Phase 3a Slice 2 — MP `network.WLAN` adapter for ESP32 (Lolin S2 MP) with `wlan.config(reconnects=0)` to disable firmware-level auto-reconnect (Decision 0029 §wifi-ownership-stance).
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
