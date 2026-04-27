# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **beginner-onramp** Step 6 — `chumicro-requests` library.  Slice 3a shipped 2026-04-26: plain HTTP GET runner-shaped (Decision 0040).  Slices 3b–3f sequenced for follow-on sessions.  Steps 1-5 (UX backbone) all shipped earlier 2026-04-26.  Remaining after Step 6: Step 7 (`chumicro-http-server`), Step 8 (examples organization + two-thing demo).  See `plans/workstreams/beginner-onramp.md`.
- **Last shipped:** Step 6 slice 3a — `chumicro-requests` plain HTTP GET against fake transport.  `HttpClient` + `RequestHandle` + `Response` + streaming `ResponseParser` + `CaseInsensitiveDict` + `WhenOversized` policy enum + `chumicro_sockets_factory()` convenience helper + `FakeHttpClient` host-only test fake.  Decision 0040 codifies the runner-shape + LED-blink invariant + adafruit_requests divergence.  100 tests at 96% combined coverage; 3 device-shipped files / 46 KB source (~70 % of mqtt's size).  Preflight green at 94 % gate.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `plans/decisions/0040-chumicro-requests.md` (new), `libraries/requests/` (new — full library scaffold + impl + tests + docs), `plans/workstreams/beginner-onramp.md` Step 6 status log, `plans/next-up.md`.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
