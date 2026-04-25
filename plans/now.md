# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 3a Slices 0–3 all shipped — every per-runtime adapter implemented and hardware-verified across all four boards.  Next: Slice 4 acceptance against a real AP (live wifi credentials needed).
- **Last shipped:** Phase 3a Slice 3 — `MpRp2WifiAdapter` (Pi Pico W CYW43) with `wlan.config(pm=0xa11140)` to disable CYW43 idle power-save (eliminates ~30-100 ms tick spikes on chip wake-up). No firmware-level supervisor on CYW43, so no `reconnects=0` call needed. 87 host tests at 99 % cov; 23 functional tests pass on Pi Pico W MP (7 RP2-adapter + 4 lazy-load + 12 no-ops for the other adapters' tests).
- **In flight:** Phase 3a Slice 4 acceptance — connect to a real AP across all four boards, observe state transitions, exercise reconnect on a deliberate disconnect.
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
