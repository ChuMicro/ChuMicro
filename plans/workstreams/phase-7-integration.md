# Workstream: Phase 7 — first sensor thing integration log

Status: `mostly resolved` — sensor thing scaffolded 2026-04-26 in `things/example_sensor/` of the canonical workspace template; end-to-end TLS+MQTT round-trip verified live on Pi Pico W RP2 with `CERT_REQUIRED` cert verification.

## Purpose

Phase 7 is the first time every chumicro library runs together against a real broker on a real board: `chumicro-wifi` brings up the radio, `chumicro-sockets` opens a TCP/TLS connection on top, `chumicro-mqtt` does CONNECT/PUBLISH/PINGREQ traffic, `chumicro-runner` schedules the lot, `chumicro-kvstore` persists a boot counter, and `chumicro-config` reads the merged `/runtime_config.msgpack`.

Each library's own test suite exercises it in isolation — typically against a fake substrate (`FakeSocket`, `FakeWifi`, `FakeTicks`).  Phase 7 surfaces *integration* concerns that no per-library suite tests: how do services hand off state, who owns reconnection, what's the right tick order, what does a partial outage look like.

This document tracks integration issues *as they're discovered*.  Each entry is one of:

- **Open** — design decision needed; sensor thing currently has a workaround / heuristic.
- **Forward-looking** — captured before they bite; revisit when a real failure mode or a second consumer surfaces.
- **Resolved** — design landed (in a Decision, in code, or in convention) with a forward link.
- **Deferred** — known-but-not-blocking; revisit when a real failure mode surfaces.

When an integration issue is resolved by changing a library API, the resolution flows back into the affected library's docs / tests so the next consumer doesn't rediscover it.

## Open

### Boot-shim deploys don't compose with import-graph resolution

**Symptom:** for the Layer-2 functional test I tried to use `thing_boot_source` (which generates the `code.py`/`main.py` + `active.py` + `workspace_runtime` shim layout) AND ship the chumicro libraries the sensor thing imports.  `thing_boot_source` doesn't take an `extra_search_paths` parameter and doesn't walk imports — it ships only the thing's own dir contents.  `thing_import_graph_source` walks imports but expects a real entrypoint file (no synthetic main.py).

**Workaround in the Layer-2 test:** the fixture writes a tiny `main.py` / `code.py` wrapper into `things/example_sensor/` whose only contents are `from app import run; run()`.  The import-graph walker starts there, finds `app`, finds the chumicro libs `app` imports, and ships everything.  The boot-shim path is bypassed entirely.

**Recommendation:** `thing_boot_source` should grow `extra_search_paths` (and probably `extra_modules`) so the boot-shim path can also walk imports for the libraries the user's `app.py` pulls in.  This unifies the two shapes — boot-shim gives you the `active.py` / `workspace_runtime` layer; import-graph just controls which files come along for the ride.  Today's CLI workaround is `python run.py deploy --import-graph <thing>`, but that gives up the boot-shim layer.

### Tick order when multiple services are ready

**Symptom:** when `runner.tick()` runs, every registered service's `check(now_ms)` is polled; the ones returning `True` get their `handle(now_ms)` called.  Order of handling is registration order (first-added → first-handled), per `chumicro-runner.core`.  In the sensor thing this is: `wifi`, `mqtt_client`, `publisher`.

**Concern:** `publisher.handle` calls `mqtt_client.publish` synchronously, which queues bytes on the socket.  If `mqtt_client.handle` ran *first* in this tick, the queue is drained before the publisher adds to it — fine.  If `publisher.handle` runs first (current order), the bytes sit in the queue until *next* tick when `mqtt_client.check` returns `True` again.  One-tick latency per publish.

**Open question:** is registration-order-defines-tick-order the intended contract, or is there a richer scheduler shape (priorities, dependencies, "drain after each handle")?

**Sensor thing's current shape:** publisher added last; one-tick latency on publish is fine (heartbeat is seconds-scale).  Concern only matters if a thing wants sub-tick-time round trips.

**Recommendation:** document the registration-order contract explicitly in `chumicro-runner`'s guide.  If it's truly the only contract, note that tasks that produce work for downstream tasks should be added *after* their consumer (counter-intuitive — flag prominently).  Or: reverse the contract (consumer-first) so producers get drained-from immediately.

### Service-state introspection vs callbacks

**Symptom:** the sensor thing polls `mqtt_client.state` from `HeartbeatPublisher.check` to gate publishing.  Equivalent: register an `on_connect` / `on_disconnect` callback on the mqtt client and toggle a publisher-internal `enabled` flag.  Both work.

**Open question:** which is the canonical pattern across chumicro?  `WifiService` exposes `on_state_change(callback)`; `MQTTClient` exposes `on_connect` / `on_disconnect` / `on_publish`.  Polling state via `.state` and pushing via callbacks have different reasoning patterns + failure modes.

**Recommendation:** prefer polling for *gating* work (publisher decides whether to publish *now*); prefer callbacks for *side effects* (a thing logs to disk on every disconnect, regardless of where in the loop the disconnect happened).  Document this in `chumicro-runner`'s guide.

## Forward-looking

### Multi-network-service composition

**Open question (no impl yet):** the sensor thing has one networking dependency (mqtt).  Real things will compose more — mqtt + a `requests`-style HTTP fetch + an inbound HTTP server + a websocket consumer + an OTA puller.  How do these share the radio cleanly?

**Concerns to think through before the second-network-service thing surfaces:**

* **One-radio constraint.**  CircuitPython has a single `wifi.radio` per board; MicroPython has one `WLAN` per interface.  Every networking library must funnel through the same `chumicro-wifi` ownership stance — none of them open the radio directly.  The library shape we have today (factories take an injected radio / use `tcp_client_socket`) covers this; a new networking library should follow the same pattern.

* **Socket budget.**  CP's `socketpool` has a per-radio socket cap (`SocketPool.maxsockets`); MP has its own ulimit.  A thing with `MQTTClient` + `requests-style client` + `inbound_http_server` may approach the limit.  Need a workspace-level discoverable: how many concurrent sockets does this thing need?  Probably surfaces as a `chumicro-sockets` constant + a deploy-time pre-flight when total demand > runtime cap.

* **Tick-time fairness.**  The current registration-order tick contract means a slow service (a big inbound PUBLISH) blocks the runner for that one tick.  Compose three networking services and one slow handler can starve the others.  Possible answer: bounded-budget `handle(now_ms, budget_ms)` contracts that yield mid-work when the budget runs out — non-trivial, defer until measured.

* **Shared error handling.**  Every networking library wants to react to wifi-drop the same way (drop their socket, wait for `wifi.connected`, rebuild).  The `chumicro-mqtt` socket-factory + self-heal pattern (resolved below) is the prototype; the same shape should generalize so a future `requests` lib can plug in.

**Capture for now**, no implementation.  Revisit when a second networking-heavy thing exists (heartbeat publisher + an OTA poll + an HTTP status endpoint, e.g.).

### LED / UX hooks for service state

**Open question (no impl yet):** users will want visual feedback for service state — an onboard LED toggling color when wifi is connecting / mqtt is reconnecting / kvstore commit failed.  Today every service exposes its own state introspection (`wifi.state`, `mqtt.state`) and callback shape (`on_state_change`, `on_connect`); there's no unified subscription point that the user's app code can hook into without writing per-library glue.

**The HAL question:** color-LED control crosses runtimes — `neopixel.NeoPixel` on CP, the `ws2812` PIO program on MP-RP2, `machine.Pin` on MP-ESP32 with discrete LEDs, no LED at all on CPython sim.  None of the chumicro libraries today own a "thing's status indicator" abstraction; users have to write the per-board code in each thing.

**Possible shapes:**

* **A pubsub layer in `chumicro-runner`** — every service emits state-change events on a shared bus; the thing subscribes once and routes events to its UX layer (LED / LCD / log).  Cleanest separation; adds a new abstraction that all libraries must learn.

* **A `StatusIndicator` HAL in `chumicro-compat`** — pluggable backends per board (neopixel, RGB pin, no-op) with a tiny color-by-state vocab (`indicator.set("connecting")`).  Things wire it manually to library callbacks (`mqtt.on_state_change(indicator.handle_mqtt_state)`).  No new bus; just a normalized output abstraction.

* **A "diagnostics console" service** — register every chumicro library with a single `Diagnostics` instance; that service drives both LED + log + REPL output uniformly.  Slightly heavier than option 2; better than option 1 for small things.

**Capture for now**, no implementation.  The sensor thing doesn't need it yet.  Revisit when a thing genuinely wants visible-from-across-the-room feedback (or when "why isn't this thing publishing?" becomes a recurring debugging question).

**Update 2026-04-27:** widened and folded into `plans/workstreams/library-pipeline.md` §"Device-feedback layer".  The new framing treats indicator LEDs as one output of a broader "device presence" layer that also covers multi-purpose buttons, status overlays on an LCD, and audible feedback — all driven by the same event stream from networking / storage / app services.  Keep this section as the historical capture; the active design lives in the library-pipeline doc.

## Resolved

### Thing directory names must follow Python identifier rules (resolved 2026-04-26)

**Symptom:** the sensor thing was originally placed at `things/example-sensor/`.  Deploy failed with `ImportError: Unresolved module dependencies: things.example-sensor.app` — Python's import system can't resolve a module path containing hyphens.

**Fix:** renamed to `things/example_sensor/` everywhere.  `chumicro-workspace new <name>` (commit `4841190`) now refuses non-identifier / leading-underscore / Python-keyword names up-front with a clear error message — no more "deploy fails on `ImportError`" surprises an hour later.

### `chumicro-deploy` import-graph misses lazy-imported per-runtime adapters (resolved 2026-04-26)

**Symptom:** the sensor thing's `from chumicro_sockets import tcp_client_socket` triggered `from chumicro_sockets._adapters import mp` *inside* the function body — Python's AST walker captured the package name (`chumicro_sockets._adapters`) but not the submodule (`mp`).  So the deploy shipped `_adapters/__init__.py` but not `_adapters/mp.py`, and the device errored out with `ImportError: no module named 'chumicro_sockets._adapters.mp'`.  Only `chumicro_sockets` had this shape — `chumicro_kvstore._backends` and `chumicro_wifi._adapters` use the deeper-import form `from chumicro_wifi._adapters.cp import CpWifiAdapter` which AST picks up directly.

**Fix:** `ImportGraphSource._imports_from_file` now also probes `{module}.{alias_name}` candidates from every `from ... import` node (commit `157a865`).  Real submodules resolve and ship; class/function names hit the existing "skip silently" path.  The workaround helper `_lazy_runtime_adapter_modules()` in `test_sensor_thing_hardware.py` is gone.

**Forward-looking:** Decision 0037's `__chumicro_runtimes__` marker scan stays parked until a library actually does dynamic `importlib.import_module(...)` dispatch (which AST can't see).

### RAM mode is scoped to single-library tests, not multi-stack things (resolved 2026-04-26 by policy)

**Symptom:** the Layer-2 functional test originally tried to run on a RAM-mode device and immediately crashed with `OSError: [Errno 2] ENOENT` on `/runtime_config.msgpack`.  Diagnosis: in MP RAM mode, `mpremote mount` maps the host tmp dir to `/remote/` — files at `/runtime_config.msgpack` on the host are reachable from the device only at `/remote/runtime_config.msgpack`.  CP RAM mode has the same shape (inline-exec doesn't persist files to flash either).

**Fix (policy, not code):** RAM mode is deliberately scoped to *single-library unit tests* and *non-risky single-purpose functional tests*.  Multi-library composition tests must run in flash mode.  Don't add `/remote/` fallback paths anywhere; that would let RAM mode silently work for cases it's not designed for.  Layer-2 tests gate on `_skip_unless_flash_mode(...)`; the same pattern belongs in any future test that depends on on-device filesystem state.

### `wifi`-drop while `mqtt` is connected — MQTT owns its bringup (resolved 2026-04-26)

**Symptom:** the sensor thing creates the MQTT socket *after* `wifi.connected == True` (early in `run()`).  If the radio later drops (deauth, AP power-cycle, signal loss), the socket the MQTT client owns silently dies — even after wifi reconnects, the existing socket can't be reused.  The thing's options were: per-thing recovery boilerplate, or no recovery.

**Fix:** `chumicro-mqtt` `MQTTClient` (commit `3f60ef4`) now optionally takes a `socket_factory: callable() -> TCPClientSocket`.  When `state == FAILED` and a factory is configured + `connect()` was originally called, the next `handle()` rebuilds the socket via the factory and re-issues `connect()` — fully self-healing without per-thing boilerplate.  Used by the example sensor thing's `_make_socket_factory(...)` closure.

### Tight tick loop is correct for networked things (resolved 2026-04-26)

An earlier draft of this entry recommended adding a `time.sleep_ms()` between ticks for battery-powered boards.  Pulled — wrong call for this stack.  Networked services need to drain inbound bytes promptly: a 100 ms sleep loses PINGRESP timing, drops reconnect-attempt deadlines, or stalls a half-buffered packet recv.  Decision 0014's runner pattern explicitly avoids interrupts; a tight `while not _SHUTDOWN_REQUESTED: runner.tick()` loop is the contract.

Battery-powered boards are a different runner shape entirely — they wake periodically, do one bounded unit of work, deep-sleep until next wake.  Out of Phase 7's scope; revisit when a battery-powered thing actually surfaces as a use case.

### Graceful exit from `while True` for tests + Ctrl-C (resolved 2026-04-26)

**Symptom:** `while True: runner.tick()` had no exit path — the test harness couldn't stop the loop without killing the python process; a REPL-driven debug session couldn't break out without disconnecting the port.

**Fix:** sensor `run()` wraps the tick loop in `try / except KeyboardInterrupt`, plus the loop reads a module-level `_SHUTDOWN_REQUESTED` flag.  Ctrl-C from the REPL raises `KeyboardInterrupt` (CP + MP both); a test environment can set `_SHUTDOWN_REQUESTED = True` on the imported module to ask the loop to stop after the next tick.  Flag is the general path; Ctrl-C is the convenient interactive path.

**Forward-looking:** the shutdown flag pattern probably belongs in `chumicro-runner` itself once a second thing wants it (e.g. `runner.request_stop()`).  Don't extract until a second consumer materializes.

### Pi Pico W MP Layer-3 broker round-trip — MP socket default-blocking mode (resolved 2026-04-26)

**Symptom:** the Layer-3 deploy succeeded, the device joined wifi (verified `sensor: wifi connected at 172.16.1.2`), reached the broker (Mosquitto's log: `New client connected from 172.16.1.2:55035 as chumicro-layer3-sensor`, `Sending CONNACK to chumicro-layer3-sensor`), and then... nothing.  The device closed the connection after exactly 5 s — `chumicro-mqtt`'s default `ack_timeout_seconds`.  Reconnect, CONNACK, 5 s, close.  Forever.  No publishes ever reached the broker.

**Root cause:** chumicro-sockets' MP adapter `connect_tcp` returned a stdlib socket left in *blocking* mode — MP defaults match CPython.  chumicro-mqtt's tick-based RX path expected EAGAIN on no-data, never a blocking recv.  So `recv_into` blocked the runner's tick, the publisher's `handle()` never fired, and after MP's hidden long-poll timed out the deadline check faulted to `FAILED`, self-heal rebuilt — same blocking mode — cycle.

**Fix (commit `1239378`):** `MQTTClient` enforces `setblocking(False)` on every socket it acquires — both the constructor's `socket=` arg and the `socket_factory()` return value.  Phase 7 Layer-3 went from 0 messages in 60 s to 4+ messages in 8 s on a Pi Pico W MP, identical sensor template, no other changes.

### TLS over MQTT on MP — recv-returns-None contract (resolved 2026-04-26)

**Symptom:** plain TCP MQTT worked after the previous fix, but TLS+MQTT didn't.  The earlier comment in `mp.py` claimed "Lolin S2 ESP32 SSLSocket drops setblocking" — verified false on MP 1.28.0 against both Pi Pico W RP2 and Lolin S2 ESP32-S2 (both expose `setblocking` per `extmod/modtls_mbedtls.c:903`).  Real divergence was elsewhere: plain TCP non-blocking `recv` raises `OSError(11)` on no-data, but mbedTLS `SSLSocket` returns `None`.  `_MpSocketWrapper.recv_into` called `len(data)` unconditionally and crashed on `len(None)` with `TypeError`.

**Fix (commit `67fb4e8`):** `_MpSocketWrapper.recv_into` treats `None` as 0 bytes — same effect as "no data this tick", which feeds straight into chumicro-mqtt's existing `if got == 0: break` path.  Stale "drops setblocking" comment removed.

End-to-end TLS+MQTT verified live: 3 PUBLISH messages with QoS-1 PUBACKs against a local self-signed broker on Pi Pico W RP2.  No new MQTT client, no blocking-mode variant.

### TLS-with-CA-verification on MP — PEM→DER conversion (resolved 2026-04-26)

**Symptom:** `verify_mode = CERT_REQUIRED` + `ssl_context_with_ca(PEM)` raised `ValueError('invalid cert')` on Pi Pico W RP2 but worked on Lolin S2 ESP32-S2.  Five PEM input shapes (bytes / str / no-trailing-newline / CRLF / single-line) all rejected on rp2; DER (binary, no PEM markers) accepted on both.

**Root cause:** rp2 MP firmware ships mbedTLS *without* `MBEDTLS_PEM_PARSE_C` (flash savings).  ESP-IDF's mbedTLS bundles it.  Without the flag, mbedTLS itself can't parse PEM and `mbedtls_x509_crt_parse` returns `MBEDTLS_ERR_X509_BAD_INPUT_DATA`.  DER skips the PEM-preprocessing step entirely.

**Fix (commit `94561f7`):** `chumicro_sockets._adapters.mp.ssl_context_with_ca` now strips the `-----BEGIN/END-----` markers + whitespace + blank lines, base64-decodes the body, passes raw DER to `load_verify_locations`.  API surface unchanged (PEM in, `str` or `bytes`).  Empirical 5-shape × 2-board table + two operational gotchas (device RTC must be set; mbedTLS errors are coarse) lifted to `plans/learnings.md` § "MP rp2 firmware ships mbedTLS without MBEDTLS_PEM_PARSE_C".

End-to-end TLS+MQTT with `CERT_REQUIRED` verified live on Pi Pico W against a local self-signed Mosquitto: 3 QoS-1 PUBLISHes round-tripped with PUBACKs.  No "blind trust" — verification is real.

## Deferred

### Multi-thing sequencing

The sensor thing is a single thing.  The diff-deploy redesign captured in `plans/next-up.md` ("Replace multi-thing staging with scoped diff-deploy") is the planned answer to "what does it mean to switch between things."  Not a Phase 7 concern; revisit when a second thing exists as a fixture.

### Time-source consistency

`chumicro-mqtt` uses `chumicro-timing`'s `ticks_ms` by default.  `chumicro-wifi` uses an internal time source via `WifiConfig`.  `HeartbeatPublisher` uses `ticks_ms` directly.  All three agree today (they all wrap `chumicro-timing` in production), but a thing that injects its own time source for testing has to thread it through every service.  Worth a uniform "time source" injection pattern in `chumicro-runner` eventually; not blocking.
