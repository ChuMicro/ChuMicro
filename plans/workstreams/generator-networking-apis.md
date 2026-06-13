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
