# Workstream: generator (`yield from`) I/O surfaces for the networking libraries

Status: **in progress** (started 2026-06-13, branch `generator-networking-apis`).

Builds on Decision 0087 (generator substrate) by giving the networking libraries the two
`yield from` surfaces that earn their place, and by fixing the demos that advertise a bad
callback cadence. Plan file: `~/.claude/plans/functional-twirling-thacker.md`.

## Problem

The networking demos read badly. `demos/mqtt_pub_sub/app.py` chains completion callbacks
(`on_connect` -> publish-retained -> `on_publish` -> subscribe -> `on_subscribe`) for what is a
linear setup, plus module-global flags. Decision 0087 built `runner.add_generator` + the socket
helpers but deferred giving the reactive networking libraries their own generator surfaces.

## Decisions (with the user, 2026-06-13)

- `yield from` earns its place in two flavors only: one-shot wait (requests `fetch`) and
  receive-stream (`websockets.next_message()`). MQTT gets **no** generator API — inbound stays
  `on_message`, connect stays `on_connect`-callback, publish/subscribe stay fire-and-forget. Its
  fix is a demo rewrite.
- http_server is out of scope (route decorators are idiomatic; only streaming bodies + the
  deferred 0081 Phase 6 TLS-accept would use generators).
- Socket helpers live in `chumicro_sockets.generators` (Option 1) — confirmed DI-safe: requests
  and websockets already depend on `chumicro-sockets`, gain no new dependency; runner depends only
  on timing, no cycle. Amends 0087's drifted text (`connect(connector)`, not `connect(host,port,radio)`).
- Demos must match real-world norms (paho/MiniMQTT, requests/httpx, the `websockets` lib) within
  MicroPython + runner constraints. Validated at four levels: unit, functional, runnable examples,
  runnable demos.

## Implementation phases

1. **Relocate socket helpers to `chumicro_sockets.generators`.** Move connect/send_all/recv_until/
   recv_exact + wait shapes from `chumicro_runner.generators`; keep `sleep_until` in runner; no
   re-export (avoids runner->sockets dep). Update the sockets_runner_connector demo import; move the
   helper unit tests + tracemalloc lane to sockets; keep the full-stack-under-Runner tests in runner.
   DI stop-clause: STOP and escalate if a top-level substrate import becomes unavoidable.
2. **chumicro_requests one-shot `fetch`.** New opt-in `generators.py`; reuse the I/O-free `_wire`
   (encode_request, ResponseParser, parse_url, resolve_redirect_url); lazy-import socket helpers.
3. **chumicro_websockets receive stream.** `next_message()` on `_BaseSession`; `InboundMessage`;
   bounded inbound deque (`max_inbound_queue_size`, drop-oldest); first use flips data delivery from
   callbacks to queue. Dual-registration (session + generator) integration test.
4. **MQTT demo rewrite.** Last Will for state, callbacks set once, no chained cadence. No lib change
   expected; add `on_connect_failed` only if the demo branches on failure.
5. **New demos + example refresh.** `demos/requests_fetch`, `demos/websockets_stream`; refresh
   touched libraries' `examples/`.
6. **Decision records.** Amend 0087 in place; new ADR for the networking generator surfaces.

## Hardware for the bake

CircuitPython ESP32 board (register first); two MicroPython boards (`lolin-s2-mini-mp` + one more);
Pi Pico W CircuitPython back up 2026-06-13 (the 256 KB cross-runtime contract board — bake there
while it stays up). Demos run to `DEMO_COMPLETE`; tail one minute under load.

## Validation history

- 2026-06-13 Phase 1: relocation landed. `preflight --coverage-threshold 94` green (lint, test 96%
  total, sockets 94.92% / runner 100% on `generators.py`, test-micropython, test-circuitpython,
  check-version, check-api all PASS). Helper unit tests + tracemalloc lane on sockets (incl. two
  added non-EAGAIN recv-error tests); full-stack + new `sleep_until` tests on runner. 47 generator
  tests pass. Real-board bake of the sockets demo: pending (rides Phase 5's bake).
- 2026-06-13 Phase 2: `chumicro_requests.generators.fetch` (+ get/post/put/patch/delete) landed,
  reusing `_wire` and the two client helpers, lazy-importing the socket helpers (no top-level
  substrate import; `import chumicro_requests` stays sockets-free). Enabler fix in
  `chumicro_runner._GeneratorWrapper.check()`: a socket-driven wait now resumes every tick even when
  it also carries `next_deadline` (a socket read with a timeout), so ready bytes are not stalled
  until the deadline; covered by a new runner test. `preflight --coverage-threshold 94` green
  (requests 96.35% total, generators.py 100%; cross-runtime + check-version + check-api PASS).
  requests 0.13.6 -> 0.14.0; runner 0.7.0 -> 0.7.1 (check() behavior). Real-board bake: pending Phase 5.
- 2026-06-13 Phase 3: `WebSocketClient/Connection.next_message()` + `InboundMessage` + bounded inbound
  queue (`max_inbound_queue_size`, drop-oldest) landed on `_BaseSession`. First `next_message()` flips
  data-frame delivery from on_text/on_binary to the queue; control-frame callbacks stay live. The wait
  carries no `next_deadline` (the session is registered in its own right, so its deadlines gate the
  loop). Drop-oldest is the 2-arg `deque((), maxlen)` native behavior on every runtime (CPython via
  maxlen, MP/CP via the default flags=0); only the TX queue's flags=1 raises on overflow. An initial
  pass reused the flags=1 TX-queue helper + a manual evict (`test-micropython` surfaced the raise);
  the final code uses the plain 2-arg deque, validated green on the MP and CP emulators.
  `preflight --coverage-threshold 94` green (websockets 96.27% total; cross-runtime + check-* PASS).
  websockets 0.19.7 -> 0.20.0. Real-board bake (incl. the dual-registration path): pending Phase 5.
- 2026-06-13 Phase 4: `demos/mqtt_pub_sub` rewritten to a mainstream-quickstart cadence — Last Will set
  at construction, callbacks set once, all connect-time setup in one `on_connect` (publish + subscribe
  fire independently, neither waiting on the other's ack), no callback cascade. Per-call on_publish /
  on_subscribe callbacks only print markers, so the host driver's ack-timed markers are unchanged and
  `driver.py` needs no edit. No `chumicro_mqtt` code change (no VERSION bump); `on_connect_failed` not
  needed (the demo doesn't branch on connect failure). README updated (presence-via-will bullet +
  cadence description). `preflight --coverage-threshold 94` green (verify-demos parses clean). Real
  broker + board bake: Final phase.
