# ChuMicro libraries

Small, focused libraries for microcontrollers and laptops.  Use what you need — every library installs independently, depends on as little as possible, and is the same runner-shape under the hood (`check(now_ms) -> bool` + `handle(now_ms)`).

> Looking for the front door?  → [`/README.md`](../README.md) — the 8-line demo, install, and "now what?" doors.

## What's in the box?

| Library | What it does |
|---|---|
| **[timing](timing/)** | Timers that don't freeze your code — your loop keeps running while waiting.  No more `time.sleep()` locking everything up. |
| **[runner](runner/)** | A simple task scheduler — register your services, call `runner.tick()` in your loop.  No async needed. |
| **[compat](compat/)** | Standard library features that CircuitPython and MicroPython are missing (like `functools.partial`). |
| **[logging](logging/)** | Levelled logging that's runner-friendly and never blocks your loop.  Per-logger levels with hierarchy resolution; zero chumicro deps. |
| **[events](events/)** | Runner-shaped pub/sub event bus — bounded, drop-oldest, zero deps.  Wires service callbacks (e.g. wifi state changes) into application-level handlers. |
| **[msgpack](msgpack/)** | Compact binary serialization — 30–50% smaller than JSON, great for settings and sensor data.  Wire-compatible with PyPI `msgpack(use_single_float=True)`. |
| **[config](config/)** | Standardized runtime-config helpers — flat-key dotted config (`wifi.ssid`, `mqtt.broker.host`) with `<Name>Config.from_config(...)` for each consumer library. |
| **[kvstore](kvstore/)** | Tiny persistent key-value store — counters, timestamps, tokens.  Picks the right backend (NVM / NVS / LittleFS) for your board. |
| **[wifi](wifi/)** | One WiFi service across CP, MP-ESP32, and MP-Pico-W — state machine, reconnect supervisor, no firmware-level surprises. |
| **[sockets](sockets/)** | Cross-runtime TCP + TLS + UDP — one protocol per shape over CP `socketpool`, MP `socket`/`ssl`, and CPython stdlib.  Substrate for the network libraries above and below. |
| **[ntp](ntp/)** | Runner-shaped SNTP client over an injected UDP socket.  Pure-Python, cross-runtime; gets the device clock close enough for TLS validity-period checks. |
| **[requests](requests/)** | Non-blocking HTTP/1.1 client — LED keeps blinking through a TLS handshake, mid-timeout, or against a stalled peer. |
| **[http_server](http_server/)** | Non-blocking HTTP/1.1 server — `@server.route` decorator with method dispatch + path params; per-connection state machine advances one chunk per tick.  TLS-server-capable on every supported runtime/board pair *except* CP-on-rp2. |
| **[mqtt](mqtt/)** | Non-blocking MQTT 3.1.1 client (QoS 0 + 1) — runner-shaped, no threads or async.  Concurrent QoS 1 publishes, configurable oversized-message policy, last-will + retain. |
| **[websockets](websockets/)** | Non-blocking WebSocket client + server — RFC 6455 framing + masking, runner-shaped, plays alongside `chumicro-http-server` for combined HTTP/WS deployments. |

Works on ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico, Pico W), STM32, and most boards with at least 256 KB RAM and 4 MB flash.

## Install

See [`INSTALL.md`](../INSTALL.md) for the full install matrix (CircuitPython via circup, MicroPython via mip, CPython via pip, the experimental channel, pre-compiled `.mpy` bundles).

Each library's own README has a one-line install command for that library.

## Dependencies

![ChuMicro library dependency graph](../support/docs/dependency-graph.svg)

Solid arrows are strict pyproject.toml dependencies — `pip install chumicro-mqtt` brings `chumicro-sockets` and `chumicro-timing` along.  Dashed arrows are typical-wiring dependencies expressed through constructor injection — every networked service is shaped to register with `chumicro-runner` and most accept an injected `ticks_ms` callable, but the runtime objects don't `import` each other; apps wire them up.

The SVG is regenerated from each library's pyproject.toml by [`scripts/render_dep_graph.py`](../scripts/render_dep_graph.py).  Preflight runs `--check` mode so a contributor who changes a library's deps without re-rendering sees the failure in CI rather than discovering it months later.

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
- **"I want levelled logging that doesn't pull in chumicro deps"** → [logging](logging/)
- **"I want a pub/sub bus to wire wifi-state-change into app handlers"** → [events](events/)
- **"`functools.partial` doesn't exist on my board"** → [compat](compat/)

## Companion host-side tools

For deploy automation, REPL workflows, and project workspaces, see [`workbench/`](../workbench/) — those are CPython-only host tools (laptop, not device) but they live alongside the device libraries in the same repo.
