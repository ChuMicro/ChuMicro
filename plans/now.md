# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **beginner-onramp workstream COMPLETE 2026-04-27** — all eight steps shipped.  See `plans/workstreams/beginner-onramp.md`.  A user with a freshly-plugged board can now run `chumicro-workspace bootstrap --with-demo` for first-run, `chumicro-workspace new <thing>` to scaffold a new thing, and ship a sensor + display pair using the in-tree two-thing demo as the template.  The full HTTP / HTTPS / runner stack is verified live across the four-board canonical matrix (Pi Pico W CP/MP, Lolin S2 CP/MP).  Pick the next workstream from `plans/next-up.md`'s `## Next` queue.
- **Last shipped:** Step 8 — two-thing demo example pair (`libraries/http_server/examples/circuitpython_two_thing_{server,sensor}.py`).  Sensor side uses `chumicro-requests`'s runner-shaped `HttpClient.post`; server side uses `chumicro-http-server`'s `@route`-decorated `HttpServer`.  Both halves runner-shaped — LED-blink invariant holds during requests + accepts.  Verified by static-analysis verify-examples (hardware-prefixed filenames mark them CP/MP-only); not run live as a pair (the four-corner verification grid in slices 7d + 7t already covered every combination of HTTP/HTTPS × runtime × chip).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `libraries/http_server/examples/circuitpython_two_thing_*.py` (new), `libraries/http_server/README.md` + `docs/guide.md` (two-thing demo section), `plans/workstreams/beginner-onramp.md` Step 8 entry, `plans/next-up.md` workstream-closed entry, `plans/learnings.md` (ESP32-S2 HW-crypto handshake heap learning from slice 7d).

---

## Workstream summary (commits 7376b79..76441a3)

Eight steps shipped over 2026-04-26 + 2026-04-27:

* **1** firmware floor (Decision 0039) — `chumicro-workspace`'s registration warns on too-old MP/CP.
* **2** single-thing deploy default — `chumicro-workspace deploy` with no positional uses the lone thing.
* **3** add-device auto-inference — `add-device --address <port> <id>` infers runtime via probe.
* **4** bootstrap wizard — `chumicro-workspace bootstrap --with-demo` chains everything end-to-end.
* **5** demo command — `chumicro-workspace demo` deploys a baked-in print loop to validate the deploy chain.
* **6** **`chumicro-requests` v1** (Decision 0040, six slices 3a-3f) — runner-shaped HTTP/1.1 client, HTTPS via `chumicro-sockets`, POST/PUT/PATCH/DELETE + JSON, 301-308 redirects with budget, chunked transfer-encoding.  166 tests at 97 % coverage.  HTTPS live-verified on Pi Pico W CP + MP.
* **7** **`chumicro-http-server` v1** (Decision 0041, slices 7a + 7b + 7d + 7t) — runner-shaped HTTP/1.1 server, two-dict router, path parameters, 404/405 with `Allow:`.  Live-verified on the four-board matrix: HTTP works on every board, HTTPS works on 3 of 4 (ESP32-S2 + Pi Pico W MP fit; Pi Pico W CP fails post-handshake on a deeper rp2-port mbedTLS issue).  Surprise finding: ESP32-S2's HW crypto cuts the TLS handshake heap cost from 25 KB (rp2 software mbedTLS) to 1 KB.
* **8** two-thing demo — example pair in `libraries/http_server/examples/`.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
