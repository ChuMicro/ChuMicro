# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3a Slice 2 shipped — MP `network.WLAN` adapter live on Lolin S2 MP. Pi Pico W CYW43 adapter stubbed for Slice 3.
- **Last shipped:** Phase 3a Slice 2 — `MpEsp32WifiAdapter` wraps `network.WLAN(network.STA_IF)` with the supervisor convention (calls `wlan.config(reconnects=0)` once after the first successful connect to disable ESP-IDF's firmware-level auto-reconnect, per Decision 0029 §wifi-ownership-stance). 70 host tests at 99 % cov; 16 functional tests pass on Lolin S2 MP (4 lazy-load + 6 MP-ESP32-adapter + 6 CP no-ops). Tolerates older firmware that may reject `dhcp_hostname` or `reconnects` knobs.
- **In flight:** Phase 3a Slice 3 — Pi Pico W CYW43 adapter (`MpRp2WifiAdapter`) with `wlan.config(pm=0xa11140)` power-save knob.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
