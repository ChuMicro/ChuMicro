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

- 2026-06-13 Final-phase bake (real boards on the "Things Cat" test network). The first `requests_fetch`
  bake on the Pico W MP crashed in `Runner.wait` -> `poll.register` with `OSError: stream operation not
  supported`: the generator read-waits handed the chumicro_sockets *wrapper* to select.poll instead of
  the underlying pollable. Root cause + fix: every adapter socket wrapper exposes the pollable on
  `.sock`, and the connector's own `io_socket` unwraps via `.sock` correctly — but the generator
  read/write waits did not unwrap, and the reactive `io_socket` of mqtt / requests / websockets unwrapped
  via the non-existent `._sock` (so they handed back the wrapper). Harmless on CPython host tests (raw
  sockets have neither attr, so `._sock` passes through), it only bit on a real MP/CP device. Fixed all
  five sites to `.sock` (the two generator wait shapes + the three reactive `io_socket` properties).
  Also fixed a driver bug: `requests_fetch`/`websockets_stream` `--runtime` defaulted to `circuitpython`,
  conflicting with `--device <mp-board>`; now `default=None` like the mqtt driver. After the fix,
  `requests_fetch` ran green on the Pico W MP (264 KB): `WIFI_OK` -> `FETCHED status=200` -> clean exit.
  VERSION patches: sockets 0.11.1, requests 0.14.1, mqtt 0.16.6, websockets 0.20.1. preflight green.


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
  fire independently, neither waiting on the other's ack), no callback cascade. Per user feedback,
  the QoS-ack confirmation callbacks (on_publish / on_subscribe) were dropped entirely — publish and
  subscribe are fire-and-forget and the markers print at enqueue; the client tracks PUBACK / SUBACK
  internally and the app never needs to. The host driver needs no edit: its retained-state check has a
  resilience window and the host subscribes to the `demo/+/state` wildcard, so it catches the board's
  publish whether as retained-on-subscribe or as a live publish. No `chumicro_mqtt` code change (no
  VERSION bump). README updated (presence-via-will bullet + cadence). `preflight --coverage-threshold 94`
  green (verify-demos parses clean). Real broker + board bake: Final phase.
- 2026-06-13 Phase 5: new demos `demos/requests_fetch` (board does `response = yield from get(...)`
  against a stdlib host HTTP server) and `demos/websockets_stream` (board drains a stream via
  `yield from ws.next_message()`; the host server dogfoods `chumicro_websockets.WebSocketServer` on
  CPython, streaming a few messages then closing — so one demo exercises both ends). New library
  examples: `requests/examples/generator_fetch.py` and `websockets/examples/receive_stream.py`
  (both register the session/generator with a Runner). `preflight --coverage-threshold 94` green
  (16 demo files parse, verify-examples green for both new examples, lint + CHU clean). No library
  src change (no VERSION bump). Real-board bake of all three demos: Final phase.
- 2026-06-13 Phase 6: new Decision 0089 (generator surfaces on the networking libraries) records the
  invariant — `yield from` for sequential awaits, reactive fan-out stays callbacks — and the two
  flavors (requests fetch, websockets next_message) + why MQTT/http_server stay reactive. Decision 0087
  amended in place: the `ReadReady`/`WriteReady`/`Sleep` token classes with `ready()`/`result()` never
  shipped (the substrate is the duck-typed `io_*` wait protocol — user flagged the tokens as a weird
  early idea), `connect(host,port,radio)` corrected to `connect(connector)`, helper placement
  (`chumicro_sockets.generators` + runner's `sleep_until`) made accurate, and the "no migration
  mandated" consequence cross-links 0089. Same fix to the `add_generator` docstring in
  `chumicro_runner.core` (runner 0.7.1 -> 0.7.2, docstring-only patch). Separately surfaced (next-up):
  0087's async-ban *lint-rule* + deploy-refusal claims are stale (no CHU rule; asyncio is allowlisted)
  — left out of scope as a different subsystem. `preflight --coverage-threshold 94` green (CHU029/CHU019
  pass on both ADRs).
- 2026-06-13 Async-ban enforcement (user ask "please enforce the ban"): new CHU033 flags `async def` /
  `await` / `async with` / `async for` / `import asyncio` / `from asyncio` / `import uasyncio`, AST-based
  (string literals like the boot-shim's `async def run` rejection are not hit), scoped to `libraries/` /
  `support/` / `workbench/` and excluding `functional_tests/` (the websockets host echo server there is
  asyncio-based via the `websockets` PyPI package). 0087 §2 + §Consequences corrected: the lint rule now
  exists (CHU033), and the never-true deploy-bundle `asyncio*` refusal claim is dropped (the deploy
  `import_allowlist` allowlists asyncio). AGENTS.md cites CHU033. `workbench/checks` 0.12.0 -> 0.13.0.
  17 rule tests; `preflight --coverage-threshold 94` green (checks 94.17%; CHU033 fires on nothing in
  the repo, confirming the functional_tests exclusion).
