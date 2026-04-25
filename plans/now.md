# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Phase 3a closed.** All slices (0 skeleton, 1 CP, 2 MP-ESP32, 3 MP-RP2, 4 live-AP acceptance) shipped + hardware-verified across all four boards. `chumicro-wifi` is feature-complete for Phase 3a's scope.
- **Last shipped:** Phase 3a Slice 4 — live-AP acceptance + real-router-power-cycle recovery run against the user's local AP across every board.  Each board associated, got a DHCP-assigned IP, was deliberately disconnected (via `adapter.disconnect()`), and re-established the connection cleanly.  Real-router-power-cycle then exercised the substrate's actual AP-loss detection on all three substrate variants: CP `wifi.radio` (blocks in `connect()`), MP-ESP32 `network.WLAN` (raises `Wifi Internal State Error`), MP-RP2 CYW43 (silent, `isconnected()` stays False).  All three honest — no false-positive `connected`, no IP claimed when AP unreachable, clean recovery once AP returns.  Lifted to learnings: the per-substrate failure-mode delta.  Runners in `.scratch/` (gitignored).
- **In flight:** —  (between phases). Next sequenced phase is 4a (`chumicro-workspace-runtime`).
- **Blocked on:** —
- **Last touched:** `libraries/kvstore/**`, `plans/decisions/0034-kvstore-api-and-backends.md`, `plans/{now,history,next-up}.md`. Four boards plugged in: Lolin S2 CP/MP, Pi Pico W CP/MP — exercises every kvstore backend across slices 2–5.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
