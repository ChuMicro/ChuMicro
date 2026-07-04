# ChuMicro libraries

<img src="../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Small, focused libraries for microcontrollers and laptops.  Use what you need — every library installs independently, depends on as little as possible, and follows the same `check(now_ms) -> bool` + `handle(now_ms)` tick contract so [`runner`](runner/) can drive them uniformly.

<br clear="left">

> Looking for the project README?  → [`/README.md`](../README.md) — 8-line demo, install, and next-step pointers.
>
> Looking for host-side tools?  → [`/workbench/`](../workbench/) — laptop tools for deploy, REPL, and project workspaces.

## What's in the box?

| Library | What it does |
|---|---|
| **[timing](timing/)** | Timers that don't freeze your code — your loop keeps running while waiting.  No more `time.sleep()` locking everything up. |
| **[runner](runner/)** | A simple task scheduler — register your services, call `runner.tick()` in your loop.  No async needed. |
| **[compat](compat/)** | Standard library features that CircuitPython and MicroPython are missing (like `functools.partial`). |
| **[logging](logging/)** | Leveled logging that's runner-friendly and never blocks your loop.  Per-logger levels with hierarchy resolution; zero chumicro deps. |
| **[msgpack](msgpack/)** | Compact binary serialization — 30–50% smaller than JSON, great for settings and sensor data.  Wire-compatible with PyPI `msgpack(use_single_float=True)`. |
| **[config](config/)** | Type-checked runtime config with a shared dotted-key shape (`wifi.ssid`, `mqtt.broker.host`); each library reads its settings via `<Name>Config.from_config(...)`. |
| **[kvstore](kvstore/)** | Tiny persistent key-value store — counters, timestamps, tokens.  Picks the right backend (NVM / NVS / LittleFS) for your board. |
| **[wifi](wifi/)** | One WiFi service across CircuitPython, MicroPython on ESP32, and MicroPython on Pi Pico W — state machine, reconnect supervisor, no firmware-level surprises. |
| **[sockets](sockets/)** | Cross-runtime TCP + TLS + UDP — one protocol per shape over CP `socketpool`, MP `socket`/`ssl`, and CPython stdlib.  Substrate for the network libraries above and below. |
| **[ntp](ntp/)** | Runner-shaped SNTP client over an injected UDP socket.  Pure-Python, cross-runtime; gets the device clock close enough for TLS validity-period checks. |
| **[requests](requests/)** | Non-blocking HTTP/1.1 client — LED keeps blinking through a TLS handshake, mid-timeout, or against a stalled peer. |
| **[http_server](http_server/)** | Non-blocking HTTP/1.1 server — `@server.route` decorator with method dispatch + path params; per-connection state machine advances one chunk per tick.  Serves TLS on every supported runtime/board pair *except* CircuitPython on RP2040/RP2350 (rp2 port). |
| **[mqtt](mqtt/)** | Non-blocking MQTT 3.1.1 client (QoS 0 + 1) — runner-shaped, no threads or async.  Concurrent QoS 1 publishes, configurable oversized-message policy, last-will + retain. |
| **[websockets](websockets/)** | Non-blocking WebSocket client + server — RFC 6455 framing + masking, runner-shaped, plays alongside [`http_server`](http_server/) for combined HTTP/WS deployments. |

Validated on ESP32 (S2, S3, C3, C6) and RP2040 / RP2350 (Raspberry Pi Pico, Pico W).  Should work on any board that runs CircuitPython or MicroPython with at least 256 KB of RAM and 2 MB physical / ~800 KB usable flash — STM32 and nRF52840 builds included, untested.

## Install

See [`INSTALL.md`](../INSTALL.md) for the full install matrix (CircuitPython via circup, MicroPython via mip, CPython via pip, the experimental channel, pre-compiled `.mpy` bundles).

Each library's own README has a one-line install command for that library.

## Dependencies

The stack runs roughly bottom-up:

- **Primitives:** `timing`, `runner`, `compat`, `logging`.  Depended-on by most others.
- **Persistence and serialization:** `msgpack`, `config`, `kvstore`.
- **Networking transport and protocols:** `wifi` (link), `sockets` (TCP / TLS / UDP), then the app protocols `ntp`, `requests`, `http_server`, `websockets`, and `mqtt`.

![ChuMicro library dependency graph](../support/docs/dependency-graph.svg)

Solid arrows are strict pyproject.toml dependencies — `pip install chumicro-mqtt` brings `chumicro-sockets` and `chumicro-timing` along.  Dashed arrows are typical-wiring dependencies expressed through constructor injection — every networked service registers with `chumicro-runner` and most accept a `ticks_ms` function as a parameter, so the runtime objects don't `import` each other; apps wire them up.

The SVG is regenerated from each library's pyproject.toml by [`scripts/render_dep_graph.py`](../scripts/render_dep_graph.py).

## Pick by problem

- **"I need timers that don't freeze my loop"** → [timing](timing/)
- **"I have multiple things happening in my loop"** → [runner](runner/) (includes timing)
- **"I need to store settings or send data compactly"** → [msgpack](msgpack/)
- **"I need to read deploy-time config on the device"** → [config](config/) (with [msgpack](msgpack/))
- **"I need to persist a counter across reboots"** → [kvstore](kvstore/)
- **"I need WiFi that auto-reconnects without surprises"** → [wifi](wifi/)
- **"I need a TCP / TLS / UDP socket that works on CP and MP"** → [sockets](sockets/)
- **"I need to set the device clock from an NTP server"** → [ntp](ntp/)
- **"I need to fetch a URL without blocking my loop"** → [requests](requests/)
- **"I need to expose HTTP routes on the device"** → [http_server](http_server/)
- **"I need an MQTT client that doesn't freeze my loop"** → [mqtt](mqtt/)
- **"I need a WebSocket client or server"** → [websockets](websockets/)
- **"I want leveled logging that doesn't pull in chumicro deps"** → [logging](logging/)
- **"I want to wire wifi-state-change into app handlers"** → direct `on_state_change` callbacks, or `chumicro_timing.waits.Signal` for generator tasks
- **"`functools.partial` doesn't exist on my board"** → [compat](compat/)
