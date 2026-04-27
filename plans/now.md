# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **beginner-onramp** Step 6 — `chumicro-requests` library.  Slices 3a (plain HTTP GET) + 3b (body decode) + 3c (HTTPS, live-board-verified) all shipped 2026-04-26.  Three remaining: 3d (POST + JSON helpers) → 3e (redirects) → 3f (chunked transfer-encoding) → Step 7 (`chumicro-http-server`) → Step 8 (examples org + two-thing demo).  See `plans/workstreams/beginner-onramp.md`.
- **Last shipped:** Step 6 slice 3c — HTTPS verified live on Pi Pico W CP + MP against `https://example.com/` (status 200, 540 body bytes, `CERT_REQUIRED` with CA-pinned context).  Three live-only bugs fixed: CP `del bytearray[:n]` → reassign-via-slice; MP `bytearray.clear()` → reassign-fresh; MP TLS `recv → None` conflated with peer close → wrapper now raises EAGAIN (`chumicro-sockets` 0.1.5).  Three live-board limitations documented (flash-mode required, CA-pinned context required, RTC-synced required).  117 host tests at 96 % combined coverage; preflight green at the 94 % gate.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/requests/src/chumicro_requests/_wire.py` (CP-safe slice replacement + MP-safe `clear()`), `libraries/sockets/src/chumicro_sockets/_adapters/mp.py` (raise EAGAIN on `None`), `libraries/sockets/VERSION` (0.1.4 → 0.1.5), `libraries/sockets/tests/test_mp_adapter.py` (new test for None-raises-EAGAIN), `libraries/requests/docs/guide.md` (Platform notes), `plans/decisions/0040-chumicro-requests.md` (Live-board limitations section), `plans/learnings.md` (3 entries), `plans/workstreams/beginner-onramp.md` Step 6 status log, `plans/next-up.md`.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
