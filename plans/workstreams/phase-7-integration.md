# Workstream: Phase 7 — first sensor thing integration log

Status: `in-progress` — sensor thing scaffolded 2026-04-26 in `things/example_sensor/` of the canonical workspace template.

## Purpose

Phase 7 is the first time every chumicro library runs together against a real broker on a real board: `chumicro-wifi` brings up the radio, `chumicro-sockets` opens a TCP/TLS connection on top, `chumicro-mqtt` does CONNECT/PUBLISH/PINGREQ traffic, `chumicro-runner` schedules the lot, `chumicro-kvstore` persists a boot counter, and `chumicro-config` reads the merged `/runtime_config.msgpack`.

Each library's own test suite exercises it in isolation — typically against a fake substrate (`FakeSocket`, `FakeWifi`, `FakeTicks`).  Phase 7 surfaces *integration* concerns that no per-library suite tests: how do services hand off state, who owns reconnection, what's the right tick order, what does a partial outage look like.

This document tracks integration issues *as they're discovered*.  Each entry is one of:

- **Open** — design decision needed; sensor thing currently has a workaround / heuristic.
- **Resolved** — design landed (in a Decision, in code, or in convention) with a forward link.
- **Deferred** — known-but-not-blocking; revisit when a real failure mode surfaces.

When an integration issue is resolved by changing a library API, the resolution flows back into the affected library's docs / tests so the next consumer doesn't rediscover it.

## Open

### Thing directory names must follow Python identifier rules (no hyphens)

**Symptom:** the sensor thing was originally placed at `things/example-sensor/`.  Deploy failed with `ImportError: Unresolved module dependencies: things.example-sensor.app` — Python's import system can't resolve a module path containing hyphens.

**Resolved:** renamed to `things/example_sensor/` everywhere — directory, README walkthroughs, fixture references in the chumicro mono-repo's tests.  Convention is now: thing directory names must be valid Python identifiers (letters, digits, underscores; not starting with a digit).

**Resolved (2026-04-26, commit 4841190):** `chumicro-workspace new <name>` now refuses non-identifier / leading-underscore / Python-keyword names up-front with a clear error message.  No more "deploy fails on `ImportError`" surprises an hour later.

### `chumicro-deploy` import-graph misses lazy-imported per-runtime adapters

**Symptom:** observed 2026-04-26 while wiring up Phase 7 Layer-3 against a real Pi Pico W MP board.  The sensor thing's `from chumicro_sockets import tcp_client_socket` triggers `from chumicro_sockets._adapters import mp` *inside* the function body — Python's AST walker captured the package name (`chumicro_sockets._adapters`) but not the submodule (`mp`).  So the deploy shipped `_adapters/__init__.py` but not `_adapters/mp.py`, and the device errored out with `ImportError: no module named 'chumicro_sockets._adapters.mp'`.

`chumicro_kvstore._backends` and `chumicro_wifi._adapters` were not affected: both use the deeper-import shape `from chumicro_wifi._adapters.cp import CpWifiAdapter` (module path includes the adapter), which the walker picks up directly.  Only `chumicro_sockets` used the shallower `from chumicro_sockets._adapters import mp` shape because its adapters expose top-level functions rather than a class to import.

**Resolved:** `ImportGraphSource._imports_from_file` now also probes `{module}.{alias_name}` candidates from every `from ... import` node.  When the alias names a real submodule (`chumicro_sockets._adapters.mp`) it resolves and ships; when it names a class/function (`from typing import Any` → `typing.Any`), the existing "skip silently" path drops it.  See commit landing this entry; the workaround helper `_lazy_runtime_adapter_modules()` in `test_sensor_thing_hardware.py` is gone.

**Forward-looking:** Decision 0037's `__chumicro_runtimes__` marker scan is still relevant for *truly* dynamic dispatchers (`importlib.import_module(...)` with a runtime-computed string), which AST can't see at all.  Not blocking — the current sockets / wifi / kvstore patterns are static enough that AST walking covers them.  Park the marker-scan idea for the next library that actually does dynamic dispatch.

### Boot-shim deploys don't compose with import-graph resolution

**Symptom:** for the Layer-2 functional test I tried to use `thing_boot_source` (which generates the `code.py`/`main.py` + `active.py` + `workspace_runtime` shim layout) AND ship the chumicro libraries the sensor thing imports.  `thing_boot_source` doesn't take an `extra_search_paths` parameter and doesn't walk imports — it ships only the thing's own dir contents.  `thing_import_graph_source` walks imports but expects a real entrypoint file (no synthetic main.py).

**Workaround in the Layer-2 test:** the fixture writes a tiny `main.py` / `code.py` wrapper into `things/example_sensor/` whose only contents are `from app import run; run()`.  The import-graph walker starts there, finds `app`, finds the chumicro libs `app` imports, and ships everything.  The boot-shim path is bypassed entirely.

**Recommendation:** `thing_boot_source` should grow `extra_search_paths` (and probably `extra_modules`) so the boot-shim path can also walk imports for the libraries the user's `app.py` pulls in.  This unifies the two shapes — boot-shim gives you the `active.py` / `workspace_runtime` layer; import-graph just controls which files come along for the ride.  Today's CLI workaround is `python run.py deploy --import-graph <thing>`, but that gives up the boot-shim layer.

### RAM mode is scoped to single-library tests, not multi-stack things

**Symptom (chronological):** the Layer-2 functional test originally tried to run on a RAM-mode device and immediately crashed with `OSError: [Errno 2] ENOENT` on `/runtime_config.msgpack`.  Diagnosis: in MP RAM mode, `mpremote mount` maps the host tmp dir to `/remote/` on the device — files at `/runtime_config.msgpack` on the host are reachable from the device only at `/remote/runtime_config.msgpack`, not the canonical absolute path `chumicro_config.load_runtime_config()` reads.  CP RAM mode has the same shape (inline-exec doesn't persist files to flash either).

**Resolved (policy, not code):** RAM mode is deliberately scoped to *single-library unit tests* and *non-risky single-purpose functional tests*.  Things that compose multiple libraries, read the merged runtime config, talk to wifi / mqtt / a broker — anything that depends on real on-device filesystem state — must run in flash mode.  Don't add `/remote/` fallback paths in `chumicro_config` or anywhere else; that would let RAM mode silently work for cases it's not designed for, hiding the real fact that RAM mode is a wrong fit.

**Workaround in Layer-2:** `_skip_unless_flash_mode(...)` at the top of every Layer-2 test.  Skipped tests print the policy in their reason so a contributor running on a RAM-default device sees what to change.

**Forward-looking:** the same guard belongs in any future test that exercises the runtime-config msgpack, kvstore persistence, or anything else that depends on the on-device filesystem persisting across operations.  Cheap pattern; replicate it.

### `wifi`-drop while `mqtt` is connected

**Symptom:** the sensor thing's tick loop creates the MQTT socket *after* `wifi.connected == True` (early in `run()`).  If the radio later drops (deauth, AP power-cycle, signal loss), the socket the MQTT client owns silently dies — `recv_into` returns `0` or `OSError(EAGAIN)`, `send` raises, etc.  The MQTT client's state machine reacts (likely transitions to `FAILED` or `DISCONNECTED`), but the *socket itself* is now permanently dead — even after wifi reconnects, the existing socket can't be reused.

**Open question:** who owns the bringup-after-down cycle?  Three candidate shapes:

1. **MQTT client owns its bringup**: when the MQTT client transitions to `FAILED` and the underlying socket is dead, it requests a new socket from a factory and reconnects.  Requires a socket *factory* dep instead of a constructed socket.  Cleanest from the thing's perspective; mqtt is fully self-healing.
2. **Thing orchestrates**: the thing's `run()` loop watches for `mqtt.state == FAILED`, tears down the mqtt client, rebuilds the socket, rebuilds the mqtt client.  More boilerplate per thing; every thing reimplements the recovery dance.
3. **A separate "supervisor" service**: a chumicro-supplied service that watches wifi + mqtt and orchestrates re-bringup.  Adds a new abstraction; defers the question.

**Sensor thing's current shape:** none of the above — a wifi drop will leave the mqtt client in `FAILED` and publishes will quietly stop.  Acceptable for the first deploy; not acceptable for production.

**Recommendation:** shape (1).  `chumicro-mqtt`'s `MQTTClient` should optionally take a *socket factory* (`callable() -> TCPClientSocket`) in addition to the current pre-connected socket form.  When `state == FAILED` and a factory is configured, the next `handle(now_ms)` rebuilds the socket and re-issues `connect()`.  Self-healing without per-thing boilerplate.  Defer the implementation until Phase 7 actually observes the failure on hardware (don't design without data).

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

### Tight tick loop is correct for networked things

**Earlier draft of this entry recommended adding a `time.sleep_ms()` between ticks for battery-powered boards.  Pulled — wrong call for this stack.**  Networked services (mqtt, future requests / http-server / websocket consumers) need to drain inbound bytes promptly: a 100 ms sleep is enough to lose PINGRESP timing, drop reconnect-attempt deadlines, or stall a half-buffered packet recv.  Decision 0014's runner pattern explicitly avoids interrupts; a tight `while not shutdown_requested: runner.tick()` loop is the contract, not a bug to optimize away.

**Battery-powered boards are a different shape entirely** — they wake periodically, do one bounded unit of work (one publish, one read, one OTA poll), then deep-sleep until the next wake.  That's a separate runner-shape ("scheduled-wake runner" rather than "tight-tick runner"), not a tweak to the loop.  Out of Phase 7's scope; revisit when a battery-powered thing actually surfaces as a use case.

**Resolved:** the tight loop stays.  The sensor thing's `run()` wraps it in `try / except KeyboardInterrupt` so REPL-Ctrl-C and the test harness can break the loop cleanly; the loop body itself remains busy-poll.

### Graceful exit from `while True` for tests + Ctrl-C

**Symptom:** Phase 7's first sensor thing has `while True: runner.tick()` as the main loop.  No exit path — the test harness can't stop the loop without killing the python process; a REPL-driven debug session can't break out without disconnecting the port.

**Resolved:** `run()` wraps the tick loop in `try / except KeyboardInterrupt`, plus the loop reads a module-level `_SHUTDOWN_REQUESTED` flag.  Ctrl-C from the REPL raises `KeyboardInterrupt` (CP + MP both), and a test environment can set `_SHUTDOWN_REQUESTED = True` on the imported module to ask the loop to stop after the next tick.  The flag is the more general path; Ctrl-C is the convenient path for interactive use.  `runner` itself doesn't need a shutdown concept — services keep their state when the loop exits, and an outer harness can re-enter the loop later if it wants to.

**Forward-looking:** the shutdown flag pattern probably belongs in `chumicro-runner` itself once a second thing wants it (e.g. `runner.request_stop()` + `runner.tick()` returning `True` while running, `False` once stopped).  Don't extract until a second consumer materializes.

### Multi-network-service composition (forward-looking)

**Open question (no impl yet):** the sensor thing has one networking dependency (mqtt).  Real things will compose more — mqtt + a `requests`-style HTTP fetch + an inbound HTTP server + a websocket consumer + an OTA puller.  How do these share the radio cleanly?

**Concerns to think through before the second-network-service thing surfaces:**

* **One-radio constraint.**  CircuitPython has a single `wifi.radio` per board; MicroPython has one `WLAN` per interface.  Every networking library must funnel through the same `chumicro-wifi` ownership stance — none of them open the radio directly.  The library shape we have today (factories take an injected radio / use `tcp_client_socket`) covers this; a new networking library should follow the same pattern.

* **Socket budget.**  CP's `socketpool` has a per-radio socket cap (`SocketPool.maxsockets`); MP has its own ulimit.  A thing with `MQTTClient` + `requests-style client` + `inbound_http_server` may approach the limit.  Need a workspace-level discoverable: how many concurrent sockets does this thing need?  Probably surfaces as a `chumicro-sockets` constant + a deploy-time pre-flight when total demand > runtime cap.

* **Tick-time fairness.**  The current registration-order tick contract means a slow service (a big inbound PUBLISH) blocks the runner for that one tick.  Compose three networking services and one slow handler can starve the others.  Possible answer: bounded-budget `handle(now_ms, budget_ms)` contracts that yield mid-work when the budget runs out — non-trivial, defer until measured.

* **Shared error handling.**  Every networking library wants to react to wifi-drop the same way (drop their socket, wait for `wifi.connected`, rebuild).  Today each library does its own pattern — the wifi-drop entry above proposes a socket factory on MQTTClient; the same shape should generalize so a future `requests` lib can plug in.

**Capture for now**, no implementation.  Revisit when a second networking-heavy thing exists (heartbeat publisher + an OTA poll + an HTTP status endpoint, e.g.).

### LED / UX hooks for service state (forward-looking)

**Open question (no impl yet):** users will want visual feedback for service state — an onboard LED toggling color when wifi is connecting / mqtt is reconnecting / kvstore commit failed.  Today every service exposes its own state introspection (`wifi.state`, `mqtt.state`) and callback shape (`on_state_change`, `on_connect`); there's no unified subscription point that the user's app code can hook into without writing per-library glue.

**The HAL question:** color-LED control crosses runtimes — `neopixel.NeoPixel` on CP, the `ws2812` PIO program on MP-RP2, `machine.Pin` on MP-ESP32 with discrete LEDs, no LED at all on CPython sim.  None of the chumicro libraries today own a "thing's status indicator" abstraction; users have to write the per-board code in each thing.

**Possible shapes:**

* **A pubsub layer in `chumicro-runner`** — every service emits state-change events on a shared bus; the thing subscribes once and routes events to its UX layer (LED / LCD / log).  Cleanest separation; adds a new abstraction that all libraries must learn.

* **A `StatusIndicator` HAL in `chumicro-compat`** — pluggable backends per board (neopixel, RGB pin, no-op) with a tiny color-by-state vocab (`indicator.set("connecting")`).  Things wire it manually to library callbacks (`mqtt.on_state_change(indicator.handle_mqtt_state)`).  No new bus; just a normalized output abstraction.

* **A "diagnostics console" service** — register every chumicro library with a single `Diagnostics` instance; that service drives both LED + log + REPL output uniformly.  Slightly heavier than option 2; better than option 1 for small things.

**Capture for now**, no implementation.  The sensor thing doesn't need it yet.  Revisit when a thing genuinely wants visible-from-across-the-room feedback (or when "why isn't this thing publishing?" becomes a recurring debugging question).

## Resolved

* Tight tick loop is correct for networked things — see entry above.
* `while True` -> `while not _SHUTDOWN_REQUESTED` + `KeyboardInterrupt` exit path — see entry above.

### Pi Pico W MP Layer-3 broker round-trip — MP socket default-blocking mode (resolved 2026-04-26)

**Symptom:** the Layer-3 deploy succeeded, the device joined wifi (verified `sensor: wifi connected at 172.16.1.2`), reached the broker (Mosquitto's log: `New client connected from 172.16.1.2:55035 as chumicro-layer3-sensor`, `Sending CONNACK to chumicro-layer3-sensor`), and then... nothing.  The device closed the connection after exactly 5 s — `chumicro-mqtt`'s default `ack_timeout_seconds`.  Reconnect, CONNACK, 5 s, close.  Forever.  No publishes ever reached the broker.

**Root cause:** the chumicro-sockets MP adapter's `connect_tcp` returns a stdlib socket left in *blocking* mode — MP defaults match CPython.  The chumicro-mqtt client's tick-based RX path expects EAGAIN on no-data, never a blocking recv.  So:
* Tick 1 — drain TX queue, send CONNECT.  Call ``recv_into`` — blocks (no data yet).
* CONNACK arrives, ``recv_into`` returns with the bytes.  Decoder runs, transitions to CONNECTED.
* Tick 2 — drain TX (empty), call ``recv_into`` again.  No data on the wire → blocks indefinitely.
* The blocking call holds the runner's tick.  The publisher's ``handle()`` never fires.
* MP's stdlib socket has a hidden long-poll-or-give-up after a few seconds (board / port dependent).  When that pops, the deadline check (`_check_deadlines`) sees the still-pending PUBLISH-or-PINGRESP marker, faults to `FAILED`, self-heal kicks in, reconnect.  Cycle.

**Fix (commit landing this entry):** make `MQTTClient` enforce ``setblocking(False)`` on every socket it acquires — both the constructor's `socket=` arg and the `socket_factory()` return value (used during self-heal).  Phase 7 Layer-3 went from 0 messages in 60 s to 4+ messages in 8 s on a Pi Pico W MP, identical sensor template, no other changes.

**TLS over MQTT on MP — also resolved (live-tested 2026-04-26):** the prior comment in `libraries/sockets/src/chumicro_sockets/_adapters/mp.py` claiming "Lolin S2 ESP32 SSLSocket drops setblocking" was stale.  Verified live on MP 1.28.0 against Pi Pico W RP2 *and* Lolin S2 ESP32-S2: both boards' mbedTLS `SSLSocket` expose `setblocking` (the `modtls_mbedtls.c` source confirms it's in the method table), and `setblocking(False)` is honored.  Source (`.tools/micropython-v1.26.0/extmod/modtls_mbedtls.c:903`):
```
{ MP_ROM_QSTR(MP_QSTR_setblocking), MP_ROM_PTR(&socket_setblocking_obj) },
```
The `axTLS` variant exposes it too (`extmod/modtls_axtls.c:420`).

There IS a contract divergence between plain TCP and TLS recv on MP though: plain TCP raises `OSError(11)` (EAGAIN) on no-data in non-blocking mode, but TLS `recv` returns `None` (no exception).  `chumicro_sockets._adapters.mp._MpSocketWrapper.recv_into` previously called `len(data)` unconditionally and crashed on the TLS-None return.  Fixed by treating `None` as 0 bytes — same effect as "no data this tick" — which feeds cleanly into `chumicro-mqtt`'s tick model (the existing `if got == 0: break` path).

End-to-end TLS+MQTT verified live: 3 PUBLISH messages with QoS-1 PUBACKs against a local self-signed broker on a Pi Pico W RP2 (commit landing this paragraph).  No new MQTT client needed; no separate blocking-mode variant; the chumicro-sockets MP adapter just needed the `None` handling path.

## Deferred

### Multi-thing sequencing

The sensor thing is a single thing.  The diff-deploy redesign captured in `plans/next-up.md` ("Replace multi-thing staging with scoped diff-deploy") is the planned answer to "what does it mean to switch between things."  Not a Phase 7 concern; revisit when a second thing exists as a fixture.

### Time-source consistency

`chumicro-mqtt` uses `chumicro-timing`'s `ticks_ms` by default.  `chumicro-wifi` uses an internal time source via `WifiConfig`.  `HeartbeatPublisher` uses `ticks_ms` directly.  All three agree today (they all wrap `chumicro-timing` in production), but a thing that injects its own time source for testing has to thread it through every service.  Worth a uniform "time source" injection pattern in `chumicro-runner` eventually; not blocking.
