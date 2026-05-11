<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Cross-runtime hardware utilities for CircuitPython, MicroPython, and Python.</big></strong>
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

ChuMicro is a family of small Python libraries for microcontroller projects — WiFi, MQTT, HTTP server and client, sockets, NTP, websockets, timing helpers, levelled logging, persistent storage, and more.  Each library installs on its own; pick what you need.

The same library source code runs on three Python runtimes without modification:

- **CircuitPython** on a dev board (Adafruit Feather, Raspberry Pi Pico W, …)
- **MicroPython** on a dev board (ESP32 family, RP2040 / RP2350, …)
- **CPython** on your laptop — for development, unit tests, and offline iteration

Everything is non-blocking — **no `async` / `await`, no threads**.  A WiFi reconnect, a TLS handshake, and an LED that blinks once per second all share a single `while True:` loop, taking small turns so each one keeps making progress.  This is sometimes called a "cooperative loop"; if you've written Arduino-style code, the shape will feel familiar.

## What makes ChuMicro different

- **One codebase, three Python runtimes.**  Each library is written once and runs unmodified on CircuitPython, MicroPython, and CPython.  No per-runtime forks, no shim modules, no "this works on CP but breaks on MP" gotchas.  You develop and unit-test on your laptop and ship the same source to the board.

- **Non-blocking by design.**  No `async` / `await`, no threads.  Each long-running operation — a WiFi reconnect, a TLS handshake, an HTTP request, an MQTT subscribe — yields back to your main loop in small chunks.  Other work in the same loop (an LED heartbeat, a button check, a display update, a sensor read) keeps running alongside it.  This is the "cooperative loop" pattern.  If you've written `loop()` functions for Arduino, you'll recognise the shape.

- **Iterating on real hardware is one command.**  Drop in a board, run `chumicro-workspace deploy-example <library> <example>`, and the example runs on the device.  Firmware install (UF2 or esptool), board discovery, source push, and REPL tail are all built in.  No Makefile, no manual `mpremote`, no copying files to a USB drive that mounts inconsistently.

- **Tested at every level — unit, cross-runtime, on real hardware.**  Every library has CPython unit tests for fast iteration on your laptop.  The same tests also run under MicroPython and CircuitPython's desktop builds (their "unix ports"), so "works on CPython, breaks on the device runtime" is caught before code reaches a board.  On top of that, on-device functional tests stage source onto a connected board and run in its actual Python runtime — driven from regular `pytest` via the `chumicro-pytest-device` plugin, so the same `pytest` you use locally surfaces hardware results too.  Every shipped example is also exercised on real CircuitPython and MicroPython boards before each release.

- **A real project layout when you outgrow examples.**  The [workspace template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) gives you a clone-and-go starter with a `projects/` tree, atomic deploys (so the board's FAT filesystem doesn't wear out from save-on-every-keystroke editing), a device registry shared with the deploy tools, workspace-wide config + secrets, and a `pytest` setup that runs tests both on your laptop and on the board.

- **Runs on common Python-capable dev boards.**  Validated on the ESP32 family (S2 / S3 / C3 / C6) and RP2040 / RP2350 (Raspberry Pi Pico and Pico W).  Any board that runs CircuitPython or MicroPython with at least 256 KB of RAM and 4 MB of flash should work — STM32 and nRF52840 builds included.

## From blink to a full IoT loop

A short tour of what ChuMicro code looks like.  We'll start with the simplest possible thing — a non-blocking LED blink — and finish with a four-service IoT device (WiFi + HTTP + MQTT + the LED) sharing one `while True:` loop.  The loop pattern stays identical throughout; new services just slot in alongside the existing ones.

The blink itself — the embedded version of "hello world" — toggles the onboard LED once per second **without** `time.sleep()` pausing anything else.  Same heartbeat in three flavours; the loop structure and timing API are identical, only the LED toggle changes per runtime.

**CircuitPython** — save as `code.py`, uses the onboard LED (`board.LED`):

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

**MicroPython** — save as `main.py`, uses `Pin(2)` (typical ESP32 onboard LED — adjust for your board):

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

The cooperative-loop payoff: a real WiFi connect, a real HTTP request, and the LED heartbeat all share the same `while True:` — and the LED stays smooth through both.  Here's a single program that runs on **both CircuitPython and MicroPython** — it connects to WiFi, fetches a URL every 30 seconds, and **never pauses the blink** while either of those happens.  Only the LED pin setup differs between the two runtimes; everything below the branch is identical:

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
        toggle_led()                       # toggle the onboard LED — takes microseconds, doesn't delay anything

    if fetch.poll(now) and wifi.connected and request is None:
        request = http.get("http://example.com")     # every 30 s, queue a fetch for example.com

    if request is not None:                # if a fetch is queued or in flight,
        if http.check(now):                #   if there's network work for it this tick…
            http.handle(now)               #   …advance it by one chunk (send / recv / parse a piece)
        if request.done:                   # once the response is fully read,
            print("status:", request.result.status_code)
            request = None                 # clear the slot so the next 30 s tick can queue another fetch
```

Each pass through the loop nudges WiFi forward, toggles the LED if its 500 ms is up, decides whether to start a new fetch, and advances any fetch already in flight by one chunk.  Nothing blocks — even a slow TLS handshake or a stalled peer just means more loop passes happen, and the LED keeps ticking through all of them.

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

### Now scale it up — add MQTT and `chumicro_runner`

Once your project has more services — WiFi, an HTTP client, an MQTT client, a button, a display — hand-rolling the `if X.check(now): X.handle(now)` dispatch in the main loop gets repetitive.  **`chumicro_runner`** is a tiny scheduler that takes that dispatch off your hands: register each service once, and the main loop becomes `while True: runner.tick()`.  Here's the same scenario, **with MQTT added** alongside the HTTP fetch so the runner pattern has something to actually carry its weight:

```python
import sys, json
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService
from chumicro_requests import HttpClient
from chumicro_mqtt import MQTTClient, ProtocolState

# LED setup — same per-runtime branch as before:
if sys.implementation.name == "circuitpython":
    import board, digitalio
    _led = digitalio.DigitalInOut(board.LED)
    _led.direction = digitalio.Direction.OUTPUT
    def toggle_led(now): _led.value = not _led.value
else:  # MicroPython
    from machine import Pin
    _led = Pin(2, Pin.OUT)                        # adjust pin for your board
    def toggle_led(now): _led.value(not _led.value())

# Services — all share the same wifi radio:
wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
http = HttpClient.from_config({}, radio=wifi.adapter.radio)
mqtt = MQTTClient.from_config({
    "mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 1883,
    "mqtt.client_id": "demo-device",
}, radio=wifi.adapter.radio)
mqtt.on_message = lambda topic, payload: print(f"command: {topic} <- {payload!r}")
mqtt.connect()                                    # non-blocking; runner drives handshake + retry

# Periodic HTTP fetch — state held in a module-level slot:
request = None

# Runner calls this every 30 s — if no fetch is in flight and wifi is up, queue a new one:
def start_fetch(now):
    global request
    if request is None and wifi.connected:
        request = http.get("http://example.com")

# Runner asks this every tick — True once a queued fetch has finished receiving its response:
def response_ready(now):
    return request is not None and request.done

# Runner calls this when response_ready() returns True — print the status, clear the slot:
def print_response(now):
    global request
    print("fetch:", request.result.status_code)
    request = None

# Runner calls this every 5 s — if MQTT is connected, publish a telemetry heartbeat (else skip this tick):
def publish_telemetry(now):
    if mqtt.state == ProtocolState.CONNECTED:
        mqtt.publish("demo/telemetry", json.dumps({"uptime_ms": now}).encode(), qos=0)

# Wire everything to one runner — order doesn't matter; each task gets a turn each tick:
runner = Runner()
runner.add(wifi)                                        # wifi state machine + reconnect
runner.add(http)                                        # advance any in-flight HTTP request
runner.add(mqtt)                                        # advance MQTT (handshake, publish, recv)
runner.add_periodic(start_fetch, period_ms=30_000)      # fetch example.com every 30 s
runner.add(response_ready, handler=print_response)      # print + clear when each response lands
runner.add_periodic(publish_telemetry, period_ms=5_000) # publish heartbeat every 5 s
runner.add_periodic(toggle_led, period_ms=500)          # toggle LED every 500 ms

# Each tick, Runner gives every registered task a turn:
while True:
    runner.tick()
```

Same cooperative loop, same per-tick advancement — every registered task still gets a turn each tick, still yields after one chunk of work.  **Four services + four periodic / conditional tasks** all sharing one `while True: runner.tick()` line — the dispatch lives in a handful of declarative registrations up front, instead of growing the loop body with another `if X.check(now): X.handle(now)` for every new service you add.  Add a button, a display, an NTP client — each is one more `runner.add(...)`, not three more lines inside the loop.

See [`libraries/timing/examples/`](libraries/timing/examples/) for debounce, multi-heartbeat, timeout, and periodic-tick patterns; [`libraries/requests/examples/`](libraries/requests/examples/) for runnable versions of the fetch pattern; and [`libraries/runner/examples/`](libraries/runner/examples/) for the full runner-registration cookbook.

## Install

If you're already working in a project (yours, or someone else's), and you just want to drop in one ChuMicro library:

```bash
# CircuitPython — via the circup bundle manager
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing

# MicroPython — via mip
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython — via pip
pip install chumicro-timing
```

Substitute the library name you want (e.g. `chumicro-mqtt`, `chumicro-wifi`).  For the full install matrix, pre-compiled `.mpy` bundles, and the experimental release channel, see [`INSTALL.md`](INSTALL.md).

If you're **starting a new project from scratch** — your own source layout, your own deploys, multiple boards or projects — see [Start a new project](#start-a-new-project) further down.

## Libraries

These libraries run on a board (or on your laptop, when developing).  Each one installs independently and pulls in as few other libraries as possible — so you can drop in just `timing` for a single sensor sketch, or pull in the whole stack for a connected device.

| Library | What it's for |
|---|---|
| **[timing](libraries/timing/)** | Periodic timers and millisecond clock math that don't block the loop.  Reach for it when you want "every 5 seconds, read the sensor" or "if no response in 2 seconds, give up" — without ever calling `time.sleep()`. |
| **[runner](libraries/runner/)** | A tiny task scheduler.  Register the services you want to run (WiFi, MQTT, your app logic, …), call `runner.tick()` from your main loop, and it gives each one a turn.  The glue that lets several libraries share the same `while True:` cleanly. |
| **[compat](libraries/compat/)** | A few Python standard-library features that CircuitPython and MicroPython don't ship (like `functools.partial`).  Use it when you want one piece of code to work across all three runtimes. |
| **[logging](libraries/logging/)** | Levelled logging (DEBUG / INFO / WARNING / ERROR / CRITICAL) that yields between records, so it doesn't pause the rest of your program.  Per-logger levels with parent-name resolution; no dependencies on other ChuMicro libraries. |
| **[events](libraries/events/)** | A small pub/sub event bus.  Wire callbacks for things like "WiFi just connected" or "received a new sensor reading" into your application logic without coupling every component to every other. |
| **[msgpack](libraries/msgpack/)** | Binary serialization — 30–50 % smaller than JSON.  Use it for saving settings, sensor data, or compact MQTT payloads.  Wire-compatible with the PyPI `msgpack` library (`use_single_float=True`). |
| **[config](libraries/config/)** | Type-checked runtime configuration.  Each library reads its settings from a shared config object using dotted keys (`wifi.ssid`, `mqtt.broker.host`), so you don't repeat parsing logic in every project. |
| **[kvstore](libraries/kvstore/)** | A tiny key-value store for boot counters, last-seen timestamps, auth tokens — small bits of state that need to survive a reboot.  Picks the right storage backend automatically (NVM on CircuitPython, NVS on ESP32 MicroPython, LittleFS elsewhere). |
| **[wifi](libraries/wifi/)** | A single WiFi service that works the same across CircuitPython (Adafruit boards) and MicroPython on both ESP32 and Pi Pico W.  Connects, reconnects on drop, and surfaces state changes as events you can wire into the rest of your app. |
| **[sockets](libraries/sockets/)** | TCP, TLS, and UDP socket helpers that work the same across all three runtimes.  Used internally by `requests`, `mqtt`, `http_server`, `websockets`, and `ntp`; usable directly when you want raw sockets.  Custom-CA TLS (an internal broker, a self-signed cert) is supported via `ssl_context_with_ca(...)` — see [`libraries/sockets/examples/tls_with_custom_ca.py`](libraries/sockets/examples/tls_with_custom_ca.py) for the pattern. |
| **[ntp](libraries/ntp/)** | Time sync over SNTP.  Gets your board's clock close enough to UTC for TLS certificate-validity checks and timestamped logs.  Pure Python, no native code. |
| **[requests](libraries/requests/)** | Non-blocking HTTP/1.1 client.  The LED keeps blinking through a TLS handshake, a slow response, or a peer that goes silent mid-stream. |
| **[http_server](libraries/http_server/)** | Non-blocking HTTP/1.1 server with a `@server.route` decorator (method dispatch, path parameters).  Serves TLS on every supported runtime/board pair except CircuitPython on RP2040. |
| **[mqtt](libraries/mqtt/)** | Non-blocking MQTT 3.1.1 client supporting QoS 0 and 1, last-will, retain, concurrent in-flight publishes, and TLS (MQTTS / port 8883), including bring-your-own-CA brokers via `chumicro_sockets`.  The pattern most folks reach for when a device talks to a broker. |
| **[websockets](libraries/websockets/)** | Non-blocking WebSocket client and server (RFC 6455 framing), plain (`ws://`) and TLS (`wss://`).  Works alongside `http_server` for combined HTTP + WS / HTTPS + WSS deployments. |

For a dependency graph and a "pick a library by problem" guide, see [`libraries/README.md`](libraries/).

## Deploying examples to a board

Every library above ships with runnable examples in its `examples/` folder.  If you have a microcontroller on hand, this repository can deploy any of those examples to the board directly — no need to set up a project of your own first.  Use this when you want to try a library on real hardware before adopting it, contribute to ChuMicro, or get a feel for the deploy / REPL / firmware tools.  (For real project work, see [Start a new project](#start-a-new-project) below — the per-library `examples/` folders are meant for trying things, not as the long-term home for your code.)

**Step 1.** Clone the repository and install everything into a Python virtual environment:

```bash
git clone https://github.com/ChuMicro/ChuMicro
cd ChuMicro
python3 scripts/prepare_workspace.py    # creates .venv, installs every library + workbench tool
```

`prepare_workspace.py` auto-creates a `.venv/` and installs the libraries + the host-side CLI tools (`chumicro-workspace`, `chumicro-deploy`, `chumicro-repl`) into it.  It uses `uv` if you have it, otherwise stdlib `venv`.

If you'd rather use your own Python environment (`pyenv`, `conda`, `uv`, a system Python, an existing project venv), activate it and run `python3 scripts/run.py setup` instead — that skips the venv-creation step and installs everything into whichever interpreter is active.

**Step 2.** Plug in a board that already runs CircuitPython or MicroPython, then ask `chumicro-workspace` to deploy an example.  The first positional is a library name (from the table above), the second is an example file's stem (from that library's `examples/` folder):

```bash
chumicro-workspace deploy-example timing heartbeat_blink
chumicro-workspace deploy-example mqtt   telemetry
chumicro-workspace deploy-example wifi   connect_to_ap
```

On the first run, you'll be walked through picking the right serial port, probing the board to detect whether it's CircuitPython or MicroPython, and remembering the board for future commands.  After that, `deploy-example` just deploys.

`chumicro-workspace deploy-example --list` prints every available `<library> <example>` pair you can run.  If you'd prefer to do the register-the-board step up front (and ship a built-in demo at the same time), run `chumicro-workspace bootstrap` first — same wizard, just standalone.

<!-- TODO(gif): terminal capture — clone → prepare_workspace → deploy-example → blinking LED. -->

**If your board is still running its factory firmware (Arduino-style, or a bare chip with no Python on it yet)**, you'll need to flash CircuitPython or MicroPython onto it first.  The wizard above can't help yet — there's no Python on the board for it to probe, and `chumicro-workspace install-firmware` won't run against an unregistered board.  Use the lower-level **`chumicro-deploy flash-firmware`** CLI instead, which takes an explicit serial port (or UF2 bootloader-drive path) and a firmware URL.  Exact flags vary by chip family (UF2 for RP2040 / RP2350; `esptool` for ESP32 boards):

```bash
chumicro-deploy flash-firmware --help    # full flag reference per method
```

Once the firmware lands and the board reboots, the `chumicro-workspace deploy-example` step above works as written — the wizard detects the freshly-flashed board and registers it on first run.

<!-- TODO(gif): flash-firmware on an Arduino-flashed board, then deploy-example. -->

Few CircuitPython / MicroPython projects let you go from a fresh `git clone` to a running on-device example this quickly — and across both runtimes from a single tree.  That's the bar this repository aims for.

## Running tests

ChuMicro's test setup runs at four levels.  All four are driven through `python3 scripts/run.py <task>` — the same entry point CI uses — so anything that passes here is what's enforced on every commit.  Bare `pytest` works too: run it from the repo root or any subdirectory and it discovers tests based on where you are (great for IDE Testing-panel runs and quick ad-hoc loops).  Only `run.py` enforces per-library coverage thresholds, so use it for commit-gating runs.

**Unit tests (CPython).**  Fast.  Run on your laptop in seconds.  Use these while iterating on library code:

```bash
python3 scripts/run.py test                         # changed packages only (default)
python3 scripts/run.py test --all                   # full sweep across every library + workbench tool
python3 scripts/run.py test --libraries timing,mqtt # scoped to specific libraries
python3 scripts/run.py test -k test_heartbeat_poll  # filter by test name
```

**Cross-runtime unit tests.**  Same library tests, executed inside MicroPython and CircuitPython's desktop builds ("unix ports").  Catches "works under CPython, breaks under MicroPython's tricks" before any code reaches a board.  Runs all three runtimes in parallel:

```bash
python3 scripts/run.py test-all-runtimes           # CPython + MicroPython + CircuitPython
python3 scripts/run.py test-micropython            # MicroPython unix-port only
python3 scripts/run.py test-circuitpython          # CircuitPython unix-port only
```

The first run builds the unix-port binaries under `.tools/` (gitignored, ~1 minute); subsequent runs reuse them.

**On-device functional tests.**  Runs real `pytest` test files on a **connected microcontroller**.  When `pytest` finds a test under a `functional_tests/` directory, the `chumicro-pytest-device` plugin stages the test source onto a board you've registered, runs it inside the device's Python runtime, and reports the result back to your pytest run — same interface as the host tests.  You'll need a board plugged in and registered (see [Deploying examples to a board](#deploying-examples-to-a-board) above):

```bash
python3 scripts/run.py test-functional             # every hardware-gated suite
python3 scripts/run.py test-libraries-functional   # only library functional tests
python3 scripts/run.py test-workbench-functional   # only workbench host-side tests that drive a board
```

**Full CI mirror.**  The same gate CI runs on every commit — lint + every test layer + docs build + import-check of every shipped example:

```bash
python3 scripts/run.py preflight                   # everything that doesn't need hardware
python3 scripts/run.py preflight --with-functional # also runs the on-device suites
```

## Workbench tools

These are command-line tools that run on **your laptop**, not on the board.  You don't need them to use the libraries above — they're optional — but they're what turns flashing firmware, deploying source code, and reading a board's output into one command each, consistently across different boards and runtimes.  The [`deploy-example` commands](#deploying-examples-to-a-board) you ran above are thin wrappers around these tools.

| Tool | What it does |
|---|---|
| **[chumicro-deploy](workbench/deploy/)** | The low-level board interaction: probe a board to ask "what runtime and version are you running?", push source code, flash firmware (UF2 file or via `esptool`).  When something goes wrong, it tries to classify the failure and tell you what to do about it (drive not mounted, board in bootloader mode, port held by another process, …). |
| **[chumicro-repl](workbench/repl/)** | A serial REPL with syntax-highlighted traceback display, a `mpremote`-compatible TUI, and a `tail()` follow-mode that streams a board's output to your terminal.  Also exposes a programmatic `ReplSession` if you want to drive a board from a Python script or test fixture. |
| **[chumicro-workspace](workbench/workspace/)** | The umbrella CLI for project workflows: scaffold a new project, install firmware, deploy one or many projects to one or many boards, open a REPL, register a new board, run lint + tests, do health checks (`status`, `doctor`).  This is the tool you'll use most.  Both this repository (when you run `deploy-example` here) and the workspace template use it. |
| **[chumicro-pytest-device](workbench/pytest-device/)** | A `pytest` plugin that runs tests **on a real board**.  When pytest finds a test under a `functional_tests/` folder, this plugin stages the test source onto a connected board, runs it in the device's Python runtime, and reports the result back to pytest like any other test.  Auto-registers — drop it in and it works. |

## Start a new project

For real project work — your own source layout, multiple projects, multiple boards, a test suite, CI — the **[ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template)** is a clone-and-go starter repository that's recommended even for a single project on a single board.  What you get:

- **A project tree** — `projects/<name>/` holds your code; one workspace can hold many projects across many boards.  A `rename` command moves projects cleanly when you reorganise.
- **Atomic, safer deploys** — your source stays on your laptop, in version control, and the workbench pushes it to the board on demand.  No save-on-every-keystroke editing on the board's FAT filesystem (which wears the flash and corrupts on cable jiggles), and "RAM mode" deploys give you fast iteration with *no flash writes at all*.
- **Workspace-wide config + per-project overrides** — `workspace.yml` for host-only settings, `secrets.toml` for wifi password / MQTT auth (gitignored), `project_config.toml` per project; everything deep-merges into a single config file the device reads at boot.
- **Board registry** — a `devices.yml` file remembers which boards you've registered, so every CLI knows which port and runtime to use.
- **Tests on the laptop *and* on the board** — `pytest` for fast unit tests, `chumicro-pytest-device` for tests that run on real hardware, and a workspace-level `preflight` (lint + tests) you can hook into CI.
- **No `pip install` prerequisite** — `python3 run.py setup` self-bootstraps a virtual environment, installs everything, and materializes the templated config files.  System Python 3.11+ is enough.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workspace-Template my-workspace
cd my-workspace && rm -rf .git && git init     # start your own git history
python3 run.py setup                           # creates .venv, installs everything
python3 run.py bootstrap                       # pick a port, register the board, ship the demo
```

See the workspace template's [README](https://github.com/ChuMicro/ChuMicro-Workspace-Template#readme) for the full walkthrough, the `example_sensor` reference project (WiFi → MQTT heartbeat with a persistent boot counter), and the multi-board / multi-project flow.

## Documentation

📖 **[chumicro.github.io/ChuMicro](https://chumicro.github.io/ChuMicro/)** — full hosted docs.  Each library has its own guide and API reference, with a version selector for switching between stable and experimental.

Workbench tools have their own hosted docs, linked from each tool's row in the [Workbench tools](#workbench-tools) table above.

## Repository layout

If you've cloned the repo and want a map of what's where:

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

## Contributing

Issues, bug reports, and pull requests are welcome.  See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the human contributor guide, or [`AGENTS.md`](AGENTS.md) if you're using an AI coding agent.

## License

[MIT](LICENSE)
