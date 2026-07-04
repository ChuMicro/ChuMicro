<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Non-blocking libraries that run unmodified on CircuitPython, MicroPython, and CPython.</big></strong>
</p>

<p align="center"><big>
  <a href="https://chumicro.github.io/ChuMicro/">Docs</a> •
  <a href="#install">Install</a> •
  <a href="#libraries">Libraries</a> •
  <a href="#deploying-examples-to-a-board">Deploy examples</a> •
  <a href="#running-tests">Run tests</a> •
  <a href="#workbench-tools">Tools</a> •
  <a href="https://github.com/ChuMicro/ChuMicro-Workspace-Template">Workspace template</a> •
  <a href="CONTRIBUTING.md">Contributing</a> •
  <a href="https://github.com/ChuMicro/ChuMicro/issues">Issues</a>
</big></p>

---

ChuMicro is a family of small Python libraries for microcontroller projects: WiFi, MQTT, HTTP server and client, sockets, NTP, websockets, timing helpers, leveled logging, persistent storage, and more.  Each library installs on its own, so pick what you need.

The same library source code runs on three Python runtimes without modification:

- **CircuitPython** on a dev board (Adafruit Feather, Raspberry Pi Pico W, …)
- **MicroPython** on a dev board (ESP32 family, RP2040 / RP2350, …)
- **CPython** on your laptop, for development, unit tests, and offline iteration

Everything is non-blocking: **no `async` / `await`, no threads**.  Concurrent work shares a single `while True:` loop, taking small turns so each one keeps making progress.

## What makes ChuMicro different

- **One codebase, three Python runtimes.**  Each library is written once and runs unmodified on CircuitPython, MicroPython, and CPython.  No per-runtime forks, no shim modules, no "this works on CP but breaks on MP" gotchas.  Develop and unit-test on a laptop, and the same source ships to your board.

- **Non-blocking by design.**  No `async` / `await`, no threads.  Each long-running operation (a WiFi reconnect, a TLS handshake, an HTTP request, an MQTT subscribe) yields back to the main loop in small chunks.  Other work in the same loop (an LED heartbeat, a button check, a display update, a sensor read) keeps running alongside it.  Same shape as Arduino's `loop()` body.

- **Iterating on real hardware is one command.**  Drop in a board, run `chumicro-workspace deploy-example <library> <example>`, and the example runs on the device.  Firmware install (UF2 or esptool), board discovery, source push, and REPL tail are all built in.  No Makefile, no manual `mpremote`, no copying files to a USB drive that mounts inconsistently.

- **Tested at every level, through one `pytest` invocation.**  Every library has CPython unit tests for fast iteration on a laptop.  The same tests also run under MicroPython and CircuitPython's desktop builds (their "unix ports"), so "works on CPython, breaks on the device runtime" is caught before code reaches a board.  On-device functional tests stage source onto a connected board and run in its actual Python runtime.  All four paths route through regular `pytest` via the `chumicro-pytest-device` plugin, so an IDE play button drives every layer the same way.  Examples are exercised on real CircuitPython and MicroPython boards as part of the release process.

- **A real project layout once examples aren't enough.**  The [workspace template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) is a clone-and-go starter with a `projects/` tree, host-staged deploys (no save-on-every-keystroke editing on the board's FAT filesystem), a device registry shared with the deploy tools, workspace-wide config + secrets, and a `pytest` setup that runs tests both on a laptop and on the board.

- **Bring your own socket, your own clock.**  Each library accepts its I/O dependencies as constructor arguments.  `MQTTClient` takes a socket. `Heartbeat` takes a clock.  You decide what to pass.  ChuMicro provides defaults (`chumicro-sockets`, `chumicro-timing`) so minimal wiring works.  Nothing locks you in: pass a stdlib `socket.socket` for a desktop script, a wrapper around an existing networking library, or anything else that exposes the small set of methods the library needs.  Adopting just one library into an existing codebase?  [Standalone integration](docs/contributing/standalone-integration.md) is the full recipe — bring-your-own transport and clock, the measured zero-sibling import closure, and host tests with no board.  When the default is fully replaced, [Slimming Your Deploy](docs/contributing/slimming-your-deploy.md) shows how to drop `chumicro-sockets` from the on-device files too.

- **Runs on common Python-capable dev boards.**  Tested on real CircuitPython and MicroPython boards before each release.  Any board that runs CircuitPython or MicroPython with at least 256 KB of RAM and 2 MB physical / ~800 KB usable flash should work.

## From blink to a full IoT loop

A short tour of what ChuMicro code looks like.  We'll start with the simplest possible thing (a non-blocking LED blink) and finish with a four-service IoT device (WiFi + HTTP + MQTT + the LED) sharing one `while True:` loop.  The loop pattern stays identical throughout. New services just slot in alongside the existing ones.

The blink itself (the embedded version of "hello world") toggles the onboard LED once per second **without** `time.sleep()` pausing anything else.  The loop structure and timing API are identical on CircuitPython and MicroPython, only the LED toggle changes per runtime.

**CircuitPython**, save as `code.py`, uses the onboard LED (`board.LED`):

```python
import board, digitalio
from chumicro_timing import Heartbeat, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        led.value = not led.value
```

**MicroPython**, save as `main.py`, uses `Pin(2)` (typical ESP32 onboard LED, adjust for your board):

```python
from machine import Pin
from chumicro_timing import Heartbeat, ticks_ms

led = Pin(2, Pin.OUT)
heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        led.value(not led.value())
```

**CPython** — no board handy?  `print` stands in for the LED toggle, so you can run this on your laptop with `python3 hello.py`:

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        print("beat!")
```

`Heartbeat` is the timer, and `ticks_ms()` is the current time in milliseconds.

### Now drop a network request in next to it

Cooperative-loop payoff: a real WiFi connect, a real HTTP request, and the LED heartbeat all share the same `while True:`, and the LED stays smooth through both.  Here's a single program that runs on **both CircuitPython and MicroPython**. It connects to WiFi, fetches a URL every 30 seconds, and **never pauses the blink** while either of those happens.  Only the LED pin setup differs between the two runtimes. Everything below the branch is identical:

```python
import sys
from chumicro_timing import Heartbeat, ticks_ms
from chumicro_wifi import WifiConfig, WifiService
from chumicro_requests import HttpClient

# Only the LED setup differs between runtimes:
if sys.implementation.name == "circuitpython":
    import board, digitalio
    _led = digitalio.DigitalInOut(board.LED)
    _led.direction = digitalio.Direction.OUTPUT
    def toggle_led():
        _led.value = not _led.value
else:  # MicroPython
    from machine import Pin
    _led = Pin(2, Pin.OUT)                 # adjust pin for your board
    def toggle_led():
        _led.value(not _led.value())

# Everything below works the same on both runtimes:
wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
http = HttpClient.from_config({}, radio=wifi.adapter.radio)
blink = Heartbeat(period_ms=500)
fetch = Heartbeat(period_ms=30_000)

request = None
while True:
    now = ticks_ms()

    if wifi.check(now):                    # if wifi has work this tick (connecting, reconnecting)…
        wifi.handle(now)                   # …do one small piece of it and return
    if blink.poll(now):                    # every 500 ms, this fires exactly once
        toggle_led()

    if fetch.poll(now) and wifi.connected and request is None:
        request = http.get("http://example.com")     # every 30 s, queue a fetch for example.com

    if request is not None:                # if a fetch is queued or in flight,
        if http.check(now):                #   if there's network work for it this tick…
            http.handle(now)               #   …advance it by one chunk (send / recv / parse a piece)
        if request.done:                   # once the response is fully read,
            print("status:", request.result.status_code)
            request = None                 # clear the slot so the next 30 s tick can queue another fetch
```

Each pass through the loop nudges WiFi forward, toggles the LED if its 500 ms is up, decides whether to start a new fetch, and advances any fetch already in flight by one chunk.  Nothing blocks. Even a slow TLS handshake or a stalled peer just means more loop passes happen, and the LED keeps ticking through all of them.

**The same pattern runs on CPython too**, where your laptop's OS already handles WiFi, so `WifiService` drops out and the LED becomes a `print`.  Useful for developing and unit-testing your loop logic before deploying:

```python
from chumicro_timing import Heartbeat, ticks_ms
from chumicro_requests import HttpClient

http = HttpClient.from_config({})
blink = Heartbeat(period_ms=500)
fetch = Heartbeat(period_ms=30_000)

request = None
while True:
    now = ticks_ms()

    if blink.poll(now):                    # every 500 ms, this fires exactly once
        print("beat!")                     # stand-in for the LED toggle

    if fetch.poll(now) and request is None:
        request = http.get("http://example.com")     # every 30 s, queue a fetch for example.com

    if request is not None:                # if a fetch is queued or in flight,
        if http.check(now):                #   if there's network work for it this tick…
            http.handle(now)               #   …advance it by one chunk
        if request.done:                   # once the response is fully read,
            print("status:", request.result.status_code)
            request = None                 # clear the slot for the next 30 s tick
```

### Now scale it up: add MQTT and `chumicro_runner`

Once your project has more services (WiFi, an HTTP client, an MQTT client, a button, a display), hand-rolling the `if X.check(now): X.handle(now)` dispatch in the main loop gets repetitive.  **`chumicro_runner`** is a tiny scheduler that takes that dispatch off your hands: register each service once, and the main loop becomes `while True: runner.tick()`.  Here's the same scenario, **with MQTT added** alongside the HTTP fetch so the runner pattern has something to actually carry its weight:

```python
import sys, json
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService
from chumicro_requests import HttpClient
from chumicro_mqtt import MQTTClient, ProtocolState

# LED setup, same per-runtime branch as before:
if sys.implementation.name == "circuitpython":
    import board, digitalio
    _led = digitalio.DigitalInOut(board.LED)
    _led.direction = digitalio.Direction.OUTPUT
    def toggle_led(now): _led.value = not _led.value
else:  # MicroPython
    from machine import Pin
    _led = Pin(2, Pin.OUT)                        # adjust pin for your board
    def toggle_led(now): _led.value(not _led.value())

# Services. All share the same wifi radio:
wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
http = HttpClient.from_config({}, radio=wifi.adapter.radio)
mqtt = MQTTClient.from_config({
    "mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883,
    "mqtt.client_id": "demo-device",
}, radio=wifi.adapter.radio)
mqtt.on_message = lambda topic, payload: print(f"command: {topic} <- {payload!r}")
mqtt.connect()                                    # non-blocking, runner drives handshake + retry

# Runner calls this when a fetch completes (success or failure):
def on_fetch_done(handle):
    if handle.error is None:
        print("fetch:", handle.response.status_code)
    else:
        print("fetch failed:", handle.error)

# Runner calls this every 30 s. If wifi is up and the client is idle, queue a fetch.
# on_done binds the response handling to the request that produced it — no shared slot,
# no separate "is the reply ready yet?" task:
def start_fetch(now):
    if wifi.connected and not http.busy:
        http.get("http://example.com", on_done=on_fetch_done)

# Runner calls this every 5 s. If MQTT is connected, publish a telemetry heartbeat (else skip this tick):
def publish_telemetry(now):
    if mqtt.state == ProtocolState.CONNECTED:
        mqtt.publish("demo/telemetry", json.dumps({"uptime_ms": now}).encode(), qos=0)

# Wire everything to one runner. Order doesn't matter, each task gets a turn each tick:
runner = Runner()
runner.add(wifi)                                        # wifi state machine + reconnect
runner.add(http)                                        # advance any in-flight HTTP request
runner.add(mqtt)                                        # advance MQTT (handshake, publish, recv)
runner.add_periodic(start_fetch, period_ms=30_000)      # fetch example.com every 30 s
runner.add_periodic(publish_telemetry, period_ms=5_000) # publish heartbeat every 5 s
runner.add_periodic(toggle_led, period_ms=500)          # toggle LED every 500 ms

# Each tick, Runner gives every registered task a turn; runner.wait
# then idles the CPU until the next socket is ready or the next
# deadline arrives, so the loop draws microamps between events:
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Same cooperative loop, same per-tick advancement: every registered task still gets a turn each tick, still yields after one chunk of work.  **Four services + three periodic tasks** all sharing one `while True:` loop. The dispatch lives in a handful of declarative registrations up front, instead of growing the loop body with another `if X.check(now): X.handle(now)` for every new service you add.  Add a button, a display, an NTP client. Each is one more `runner.add(...)`, not three more lines inside the loop.  `runner.wait(now_ms)` lets the CPU sleep between events — without it, the loop busy-polls and burns battery on a board that's mostly waiting.

For more runnable patterns, see [`libraries/timing/examples/`](libraries/timing/examples/) (debounce, multi-heartbeat, timeout, periodic ticks), [`libraries/requests/examples/`](libraries/requests/examples/) (the fetch pattern), and [`libraries/runner/examples/`](libraries/runner/examples/) (the full runner-registration cookbook).

## Install

If you're already working in a project (yours, or someone else's), and you just want to drop in one ChuMicro library:

```bash
# CircuitPython, via the circup bundle manager
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing

# MicroPython, via mip
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython, via pip
pip install chumicro-timing
```

Substitute the library name you want (e.g. `chumicro-mqtt`, `chumicro-wifi`).  For the full install matrix, pre-compiled `.mpy` bundles, and the experimental release channel, see [`INSTALL.md`](INSTALL.md).

If you're **starting a new project from scratch** (your own source layout, your own deploys, multiple boards or projects), see [Start a new project](#start-a-new-project) further down.

## Libraries

These libraries run on a board (or on your laptop, when developing).  Each one installs independently and pulls in as few other libraries as possible, so you can drop in just `timing` for a single sensor sketch, or pull in the whole stack for a connected device.

| Library | What it's for |
|---|---|
| **[timing](libraries/timing/)** | Periodic timers and millisecond clock math that don't block the loop.  Reach for it when you want "every 5 seconds, read the sensor" or "if no response in 2 seconds, give up", without ever calling `time.sleep()`. |
| **[runner](libraries/runner/)** | A tiny task scheduler.  Register the services you want to run (WiFi, MQTT, your app logic, …), call `runner.tick()` from your main loop, and it gives each one a turn.  The glue that lets several libraries share the same `while True:` cleanly. |
| **[compat](libraries/compat/)** | A few Python standard-library features that CircuitPython and MicroPython don't ship (like `functools.partial`).  Use it when you want one piece of code to work across all three runtimes. |
| **[logging](libraries/logging/)** | Leveled logging (DEBUG / INFO / WARNING / ERROR / CRITICAL) that yields between records, so it doesn't pause the rest of your program.  Per-logger levels with parent-name resolution, no dependencies on other ChuMicro libraries. |
| **[msgpack](libraries/msgpack/)** | Binary serialization that's smaller than JSON for typical sensor payloads.  Use it for saving settings, sensor data, or compact MQTT payloads.  Wire-compatible with the PyPI `msgpack` library. |
| **[config](libraries/config/)** | Type-checked runtime configuration.  Each library reads its settings from a shared config object using dotted keys (`wifi.ssid`, `mqtt.broker.host`), so you don't repeat parsing logic in every project. |
| **[kvstore](libraries/kvstore/)** | A tiny key-value store for small bits of state that need to survive a reboot: boot counters, last-seen timestamps, auth tokens.  Picks a backend based on what's available on the runtime (NVM, NVS, or a filesystem fallback). See the library guide for the current mapping. |
| **[wifi](libraries/wifi/)** | A single WiFi service that works the same across CircuitPython and MicroPython on both ESP32 and Pi Pico W.  Connects, reconnects on drop, and surfaces state changes as events you can wire into the rest of your app. |
| **[sockets](libraries/sockets/)** | TCP, TLS, and UDP socket helpers that work the same across all three runtimes.  Used internally by `requests`, `mqtt`, `http_server`, `websockets`, and `ntp`, and usable directly when you want raw sockets.  Custom-CA TLS (an internal broker, a self-signed cert) is supported via `ssl_context_with_ca(...)`. See [`libraries/sockets/examples/tls_with_custom_ca.py`](libraries/sockets/examples/tls_with_custom_ca.py) for the pattern. |
| **[ntp](libraries/ntp/)** | Time sync over SNTP.  Gets your board's clock close enough to UTC for TLS certificate-validity checks and timestamped logs.  Pure Python, no native code. |
| **[requests](libraries/requests/)** | Non-blocking HTTP/1.1 client.  The LED keeps blinking through a TLS handshake, a slow response, or a peer that goes silent mid-stream. |
| **[http_server](libraries/http_server/)** | Non-blocking HTTP/1.1 server with a `@server.route` decorator (method dispatch, path parameters).  TLS is supported where the runtime allows it. See the library guide for the current support matrix. |
| **[mqtt](libraries/mqtt/)** | Non-blocking MQTT 3.1.1 client with QoS 0 and 1, last-will, retain, concurrent in-flight publishes, and TLS (MQTTS / port 8883). |
| **[websockets](libraries/websockets/)** | Non-blocking WebSocket client and server (RFC 6455 framing), plain (`ws://`) and TLS (`wss://`).  Works alongside `http_server` for combined HTTP + WS / HTTPS + WSS deployments. |

For a dependency graph and a "pick a library by problem" guide, see [`libraries/README.md`](libraries/).

## Deploying examples to a board

Every library above ships with runnable examples in its `examples/` folder.  If you have a microcontroller on hand, this repository can deploy any of those examples to your board directly, no need to set up a project of your own first.  Use this when you want to try a library on real hardware before adopting it, contribute to ChuMicro, or get a feel for the deploy / REPL / firmware tools.  (For real project work, see [Start a new project](#start-a-new-project) below. The per-library `examples/` folders are meant for trying things, not as a long-term home for your code.)

**Step 1.** Clone the repository and install everything into a Python virtual environment:

```bash
git clone https://github.com/ChuMicro/ChuMicro
cd ChuMicro
python3 scripts/prepare_workspace.py    # creates .venv, installs every library + workbench tool
```

`prepare_workspace.py` auto-creates a `.venv/` and installs the libraries + the host-side CLI tools (`chumicro-workspace`, `chumicro-deploy`, `chumicro-repl`) into it.  It uses `uv` if you have it, otherwise stdlib `venv`.

If you'd rather use your own Python environment (`pyenv`, `conda`, `uv`, a system Python, an existing project venv), activate it and run `python3 scripts/run.py setup` instead. That skips the venv-creation step and installs everything into whichever interpreter is active.

**Step 2.** Plug in a board that already runs CircuitPython or MicroPython, then ask `chumicro-workspace` to deploy an example.  The first positional is a library name (from the table above), the second is an example file's stem (from that library's `examples/` folder):

```bash
chumicro-workspace deploy-example timing heartbeat_blink
chumicro-workspace deploy-example mqtt   telemetry
chumicro-workspace deploy-example wifi   connect_to_ap
```

On your first run, you'll be walked through picking the right serial port, probing the board to detect whether it's CircuitPython or MicroPython, and remembering the board for future commands.  After that, `deploy-example` just deploys.

`chumicro-workspace deploy-example --list` prints every available `<library> <example>` pair you can run.  If you'd prefer to do the register-the-board step up front (and ship a built-in demo at the same time), run `chumicro-workspace bootstrap` first. Same wizard, just standalone.

<!-- TODO(gif): terminal capture — clone → prepare_workspace → deploy-example → blinking LED. -->

**If your board is still running its factory firmware (Arduino-style, or a bare chip with no Python on it yet)**, you'll need to flash CircuitPython or MicroPython onto it first.  The wizard above can't help yet. There's no Python on the board for it to probe, and `chumicro-workspace install-firmware` won't run against an unregistered board.  Use the lower-level **`chumicro-deploy flash-firmware`** CLI instead, which takes an explicit serial port (or UF2 bootloader-drive path) and a firmware URL.  Exact flags vary by chip family (UF2 for RP2040 / RP2350, `esptool` for ESP32 boards):

```bash
chumicro-deploy flash-firmware --help    # full flag reference per method
```

Once the firmware lands and the board reboots, the `chumicro-workspace deploy-example` step above works as written. The wizard detects the freshly-flashed board and registers it on first run.

<!-- TODO(gif): flash-firmware on an Arduino-flashed board, then deploy-example. -->

## Running tests

ChuMicro tests at four layers: CPython unit tests, the same tests under MicroPython + CircuitPython unix-port builds, on-device functional tests on a connected board, and a full CI mirror.  Day-to-day iteration uses plain `pytest` from the repo root. The `chumicro-pytest-device` plugin transparently routes the unix-port + on-device layers through the same `pytest` invocation, so IDE play buttons work at file or function granularity across every layer.

```bash
pytest libraries/timing/tests                            # CPython unit tests
pytest libraries/ --target unix-port --runtime both      # MicroPython + CircuitPython unix-port
pytest libraries/timing/functional_tests                 # on-device, staged onto a connected board
python3 scripts/run.py preflight                         # full CI mirror (lint + every test layer + docs)
```

First-time unix-port use: run `python3 scripts/run.py prepare-micropython` and `prepare-circuitpython` once to build the binaries under `.tools/` (gitignored, ~1 minute each).

For the full reference, see [CONTRIBUTING.md › Testing](CONTRIBUTING.md#testing). It covers the `run.py` wrappers (per-library coverage gates, parallel runtime phases, PR-summary markdown, scope-by-library / file / function), `devices.yml` setup, and IDE play-button integration.

## Workbench tools

These are command-line tools that run on **your laptop**, not on the board.  You don't need them to use the libraries above (they're optional), but they're what turns flashing firmware, deploying source code, and reading a board's output into one command each, consistently across different boards and runtimes.  The [`deploy-example` commands](#deploying-examples-to-a-board) you ran above are thin wrappers around these tools.

| Tool | What it does |
|---|---|
| **[chumicro-deploy](workbench/deploy/)** | Low-level board interaction: probe a board to ask "what runtime and version are you running?", push source code, flash firmware (UF2 file or via `esptool`).  When something goes wrong, it tries to classify the failure and tell you what to do about it (drive not mounted, board in bootloader mode, port held by another process, …). |
| **[chumicro-repl](workbench/repl/)** | A serial REPL with syntax-highlighted traceback display, a `mpremote`-compatible TUI, and a `tail()` follow-mode that streams a board's output to your terminal.  Also exposes a programmatic `ReplSession` if you want to drive a board from a Python script or test fixture. |
| **[chumicro-workspace](workbench/workspace/)** | Umbrella CLI for project workflows: scaffold a new project, install firmware, deploy one or many projects to one or many boards, open a REPL, register a new board, run lint + tests, do health checks (`status`, `doctor`).  Both this repository (when you run `deploy-example` here) and the workspace template use it. |
| **[chumicro-pytest-device](workbench/pytest-device/)** | A `pytest` plugin that runs tests **on a real board**.  When pytest finds a test under a `functional_tests/` folder, this plugin stages the test source onto a connected board, runs it in the device's Python runtime, and reports the result back to pytest like any other test.  Auto-registers: drop it in and it works. |

## Start a new project

For real project work (your own source layout, multiple projects, multiple boards, a test suite, CI), **[ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template)** is a clone-and-go starter repository that's recommended even for a single project on a single board.  What you get:

- **A project tree.** `projects/<name>/` holds your code, and one workspace can hold many projects across many boards.  A `rename` command moves projects cleanly when you reorganize.
- **Atomic, safer deploys.** Your source stays on your laptop, in version control, and the workbench pushes it to the board on demand.  No save-on-every-keystroke editing on the board's FAT filesystem (which wears the flash and corrupts on cable jiggles), and "RAM mode" deploys give you fast iteration with *no flash writes at all*.
- **Workspace-wide config + per-project overrides.** `workspace.yml` for host-only settings, `secrets.toml` for wifi password / MQTT auth (gitignored), `project_config.toml` per project. Everything deep-merges into a single config file your device reads at boot.
- **Board registry.** A `devices.yml` file remembers which boards you've registered, so every CLI knows which port and runtime to use.
- **Tests on the laptop *and* on the board.** `pytest` for fast unit tests, `chumicro-pytest-device` for tests that run on real hardware, and a workspace-level `preflight` (lint + tests) you can hook into CI.
- **No `pip install` prerequisite.** `python3 run.py setup` self-bootstraps a virtual environment, installs everything, and materializes the templated config files.  System Python 3.11+ is enough.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workspace-Template my-workspace
cd my-workspace && rm -rf .git && git init     # start your own git history
python3 run.py setup                           # creates .venv, installs everything
python3 run.py bootstrap                       # pick a port, register the board, ship the demo
```

See the workspace template's [README](https://github.com/ChuMicro/ChuMicro-Workspace-Template#readme) for the full walkthrough, the `example_sensor` reference project (a WiFi-to-MQTT heartbeat with a persistent boot counter), and the multi-board / multi-project flow.

## Documentation

📖 **[chumicro.github.io/ChuMicro](https://chumicro.github.io/ChuMicro/)** for full hosted docs. Each library has its own guide and API reference, with a version selector for switching between stable and experimental.

Workbench tools have their own hosted docs, linked from each tool's row in the [Workbench tools](#workbench-tools) table above.

## Repository layout

If you've cloned the repo and want a map of what's where:

```text
chumicro/
├── libraries/             # Publishable libraries that run on microcontrollers (CP + MP + CPython)
├── workbench/             # Publishable host-only tools that run on a laptop (CPython only)
├── support/               # Internal packages (docs assets, test harness), never published
├── scripts/               # Developer tasks (run.py is the entry point)
├── docs/contributing/     # Style guide, cheat sheet, setup guides
├── plans/                 # Work queue, decisions, patterns, workstreams
├── .github/
│   ├── workflows/         # CI, release, promote, docs-deploy
│   └── skills/            # Agent skill instructions
├── target-runtimes.toml   # Pinned runtime versions
└── LICENSE                # MIT
```

## Contributing

Issues, bug reports, and pull requests are welcome.  See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the human contributor guide, or [`AGENTS.md`](AGENTS.md) if you're using an AI coding agent.

## License

[MIT](LICENSE)
