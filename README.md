<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Keep a status LED blinking, even through a slow network call.</big></strong>
</p>

<p align="center">
  <a href="https://chumicro.github.io/ChuMicro/">Docs</a> •
  <a href="https://github.com/ChuMicro/ChuMicro-Workspace-Template">Workspace template</a> •
  <a href="libraries/">Libraries</a> •
  <a href="workbench/">Workbench tools</a> •
  <a href="https://github.com/ChuMicro/ChuMicro/issues">Issues</a>
</p>

---

ChuMicro's WiFi, MQTT, HTTP, sockets, NTP, and websockets libraries cooperate on a single `while True:` loop.  Slow operations don't pause fast ones — a status LED, a sensor read, and a network publish all share the loop and make progress alongside each other.

No `async`/`await`, no threads.  The same library code runs on CircuitPython, MicroPython, and CPython.

## Libraries

Small, focused libraries for microcontrollers.  Each installs independently and depends on as little as possible.

| Library | What it does |
|---|---|
| **[timing](libraries/timing/)** | Wraparound-safe millisecond ticks, heartbeat scheduling, deterministic test fakes.  No more `time.sleep()` locking up the loop. |
| **[runner](libraries/runner/)** | A simple task scheduler — register a set of services, call `runner.tick()` from a `while True:` loop. |
| **[compat](libraries/compat/)** | Standard library features that CircuitPython and MicroPython are missing (like `functools.partial`). |
| **[logging](libraries/logging/)** | Levelled logging that's runner-friendly and never blocks the loop.  Per-logger levels with hierarchy resolution; zero chumicro deps. |
| **[events](libraries/events/)** | Runner-shaped pub/sub event bus — bounded, drop-oldest, zero deps.  Wires service callbacks (e.g. wifi state changes) into application-level handlers. |
| **[msgpack](libraries/msgpack/)** | Compact binary serialization — 30–50% smaller than JSON, great for settings and sensor data.  Wire-compatible with PyPI `msgpack(use_single_float=True)`. |
| **[config](libraries/config/)** | Standardized runtime-config helpers — flat-key dotted config (`wifi.ssid`, `mqtt.broker.host`) with `<Name>Config.from_config(...)` for each consumer library. |
| **[kvstore](libraries/kvstore/)** | Tiny persistent key-value store — counters, timestamps, tokens.  Picks the right backend (NVM / NVS / LittleFS) per board. |
| **[wifi](libraries/wifi/)** | One WiFi service across CP, MP-ESP32, and MP-Pico-W — state machine, reconnect supervisor, no firmware-level surprises. |
| **[sockets](libraries/sockets/)** | Cross-runtime TCP + TLS + UDP — one protocol per shape over CP `socketpool`, MP `socket`/`ssl`, and CPython stdlib.  Substrate for the network libraries. |
| **[ntp](libraries/ntp/)** | Runner-shaped SNTP client over an injected UDP socket.  Pure-Python, cross-runtime; gets the device clock close enough for TLS validity-period checks. |
| **[requests](libraries/requests/)** | Non-blocking HTTP/1.1 client — the LED keeps blinking through a TLS handshake, mid-timeout, or against a stalled peer. |
| **[http_server](libraries/http_server/)** | Non-blocking HTTP/1.1 server — `@server.route` decorator with method dispatch + path params; per-connection state machine advances one chunk per tick.  TLS-server-capable on every supported runtime/board pair *except* CP-on-rp2. |
| **[mqtt](libraries/mqtt/)** | Non-blocking MQTT 3.1.1 client (QoS 0 + 1).  Concurrent QoS 1 publishes, configurable oversized-message policy, last-will + retain. |
| **[websockets](libraries/websockets/)** | Non-blocking WebSocket client + server — RFC 6455 framing + masking, plays alongside `chumicro-http-server` for combined HTTP/WS deployments. |

Works on ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico, Pico W), STM32, and most boards with at least 256 KB RAM and 4 MB flash.

[See `libraries/README.md`](libraries/) for a dependency graph and a "pick by problem" selection guide.

## Workbench tools

Host-side tools that run on a laptop, not the device.  Optional — the libraries above work without them.

| Tool | What it does |
|---|---|
| **[deploy](workbench/deploy/)** | Push code onto a CircuitPython or MicroPython board, probe identity, flash firmware (UF2 or esptool).  Programmatic API + `chumicro-deploy` CLI; recovery layer that classifies failures and points at the right fix. |
| **[repl](workbench/repl/)** | Serial REPL with traceback highlighting, an `mpremote`-compatible TUI, a `tail()` follow-mode for deploy orchestration, and a programmatic `ReplSession` for headless test fixtures.  `chumicro-repl` CLI. |
| **[workspace](workbench/workspace/)** | One-stop host CLI + Python API for ChuMicro project workspaces — `init` (clone a starter), `setup` (bootstrap a venv), `add-device`, `deploy` (single project, `--all-devices`, or `--all-projects`), `repl <project>` (deploy-then-tail), `install-firmware`, `status` / `doctor` health checks, `new --library` / `new --from`, path-aware `rename`, `update` (re-flow tool-owned template files).  Canonical starter lives at [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template). |
| **[pytest-device](workbench/pytest-device/)** | Pytest plugin that intercepts collection under any `functional_tests/` directory, stages library + test source onto a connected CP / MP board via `chumicro-deploy`, runs the test in the device runtime, and surfaces the on-device outcome to host-side pytest.  Auto-registers via `pytest11`; reads `devices.yml`. |

## Install

```bash
# CircuitPython (via circup)
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing

# MicroPython (via mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython (via pip)
pip install chumicro-timing
```

For pre-compiled `.mpy` bundles, the experimental channel, and the full install matrix, see [`INSTALL.md`](INSTALL.md).

The recommended path for a new project is the [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) starter — clone-and-go, even for a single-project board (no live editing on CIRCUITPY means no FAT-filesystem wear and no losing files when the drive hiccups).

## Documentation

📖 **[chumicro.github.io/ChuMicro](https://chumicro.github.io/ChuMicro/)** — guides, API references, and examples for every library.  Each library has its own docs with a version selector for switching between stable and experimental.

## Repository layout

```text
chumicro/
├── libraries/             # Publishable libraries that run on microcontrollers (CP + MP + CPython)
├── workbench/             # Publishable host-only tools that run on a laptop (CPython only)
├── support/               # Internal packages (docs assets, test harness) — never published
├── scripts/               # Developer tasks (run.py is the entry point)
├── docs/contributing/     # Style guide, cheat sheet, setup guides
├── plans/                 # Work queue, decisions, patterns, workstreams
├── .github/
│   ├── workflows/         # CI, release, promote, docs-deploy
│   └── skills/            # Agent skill instructions
├── target-runtimes.toml   # Pinned runtime versions
└── LICENSE                # MIT
```

## License

[MIT](LICENSE)
