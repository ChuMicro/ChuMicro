# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **beginner-onramp** Step 6 — `chumicro-requests` library.  Slices 3a (plain HTTP GET) + 3b (body decode → `.text` / `.json()` / charset sniff) shipped 2026-04-26.  Slice 3c (HTTPS, live-board verification on the four-board matrix) is next.  Then 3d (POST + JSON helpers) → 3e (redirects) → 3f (chunked transfer-encoding decode) → Step 7 (`chumicro-http-server`) → Step 8 (examples org + two-thing demo).  See `plans/workstreams/beginner-onramp.md`.
- **Last shipped:** Step 6 slice 3b — body decode.  `Response.encoding` (sniffed from Content-Type charset, default utf-8, settable for server-lies cases), `Response.text` (UnicodeDecodeError-on-mismatch), `Response.json()` (ValueError-on-malformed); `parse_charset()` helper in `_wire.py` exposed publicly.  115 tests at 97 % combined coverage; preflight green at the 94 % gate.
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/requests/src/chumicro_requests/_wire.py` (parse_charset), `libraries/requests/src/chumicro_requests/client.py` (Response.encoding/text/json + json import), `libraries/requests/tests/test_requests.py` (TestParseCharset + TestResponseDecode), README + docs/guide.md + docs/index.md, `plans/workstreams/beginner-onramp.md` Step 6 status log, `plans/next-up.md`.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
