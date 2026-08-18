<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Python libraries for microcontrollers that never freeze your program.  One codebase for CircuitPython, MicroPython, and your laptop.</big></strong>
</p>

<p align="center"><big>
  <a href="https://chumicro.com/ChuMicro/">Docs</a> •
  <a href="#install">Install</a> •
  <a href="#the-libraries">Libraries</a> •
  <a href="#watch-it-work-on-real-hardware">Demos</a> •
  <a href="#start-a-real-project">Start a project</a> •
  <a href="CONTRIBUTING.md">Contributing</a> •
  <a href="https://github.com/ChuMicro/ChuMicro/issues">Issues</a>
</big></p>

---

ChuMicro is a family of small Python libraries for microcontrollers: WiFi, MQTT, HTTP client and server, WebSockets, sockets, network time, timers, configuration, and storage that survives a reboot.  Each library installs by itself, so a project that only needs a timer gets a timer and nothing else.

Three rules run through every library.

The first rule: never stop the program.  A microcontroller usually has several jobs running at once.  It keeps the WiFi alive, stays connected to an MQTT broker (the message hub most home-automation setups talk through), blinks a status LED, watches a button.  Most Python libraries for boards block: while a request waits on a slow server, or WiFi retries a dead router, the entire device freezes and every other job stops with it.  Code that stops the world to wait on a network is a bad foundation for a device, and if you've ever watched a board hang for thirty seconds because the router was unplugged, you already know it.  ChuMicro libraries do their work in small steps inside your loop.  Each pass, every library does a little and hands control back, so a dead network costs you nothing but the network: the LED keeps blinking, the button keeps answering, and you choose how long to wait and what happens when the waiting is over.

The second rule: the same code runs everywhere.  A library written for CircuitPython won't run on MicroPython, and one written for MicroPython won't run on CircuitPython, so changing boards often means porting your project.  Every ChuMicro library runs unmodified on CircuitPython, MicroPython, and the standard Python on your computer.  You can develop and test a program at your desk, then deploy the same files to a Pico W running CircuitPython or an ESP32 running MicroPython.

The third rule: your program stays yours.  Every library takes its socket and its clock as arguments you pass in, and every library moves forward when your own loop hands it a turn.  So you can run one of these inside a `while True` you already wrote and give it the socket you already have.  `import chumicro_mqtt` loads no other ChuMicro module, and supplying your own socket and clock keeps it that way.

## An LED blink without time.sleep()

The first thing every tutorial teaches is `time.sleep()`.  It's also the reason most board code can only do one thing at a time.  Here's the embedded hello world with no sleep in it:

```python
import board, digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
blink = Rate(500, ticks_ms())

while True:
    now = ticks_ms()
    if blink.due(now):
        led.value = not led.value
    # everything else your device does goes here, one small step at a time
```

The loop never pauses.  `Rate` answers "is it time yet?", the LED toggles when it is, and the loop moves on either way.  Everything in ChuMicro is built on this shape: the MQTT client, the HTTP server, and the WiFi supervisor each do one small piece of work per pass through the loop, exactly like this blink.  (CircuitPython shown; the MicroPython version differs only in the LED lines, and both ship in [timing's examples](libraries/timing/examples/).)

## Give WiFi a deadline and keep blinking

Hand your services to the `Runner` and it deals out the turns.  Here's the scenario this project measures itself against: WiFi comes up on a time budget while the LED keeps its rhythm.

```python
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="home-wifi", password="…"))

def toggle_led(now):
    led.value = not led.value      # led set up as in the blink example above

runner = Runner()
runner.add(wifi)                                  # connects, retries, reconnects on drop
runner.add_periodic(toggle_led, period_ms=500)    # blinks no matter what wifi is doing

if runner.run_until(lambda: wifi.connected, timeout_ms=20_000):
    print("online:", wifi.ip)
else:
    print("no wifi yet, starting anyway")         # wifi keeps retrying in the background

while True:
    now = runner.tick()    # every service takes one small step
    runner.wait(now)       # then the CPU idles until something actually needs it
```

Unplug the router and this program does not hang.  The LED blinks through the retries, the twenty seconds run out, and the device starts working offline.  The WiFi service keeps retrying with backoff, and when the network comes back, `wifi.connected` flips true.  The last line matters too: `runner.wait()` sleeps the CPU until the next socket event or timer deadline instead of spinning the loop flat out, and on battery that idle time is what your runtime budget is made of.

## Sequential work reads top to bottom

Some work is a sequence: connect, send, wait for the reply, read it.  Written out as callbacks and status flags, a four-step sequence scatters across a file.  This repository ships its TCP echo demo in [both styles](demos/) so you can put them side by side: the state-machine version is a class with ten methods, and the generator version is one function you read top to bottom.

A generator is plain Python.  Each `yield from` marks the line where your code pauses; the rest of the device runs; your code resumes on that line when the socket is ready.

```python
from chumicro_requests.generators import get
from chumicro_sockets.sockets_factory import connector_factory

transport_factory = connector_factory(radio=wifi.adapter.radio)

def fetch_forecast():
    response = yield from get(transport_factory, "http://example.com/")
    print(response.status_code, len(response.body))

handle = runner.add_generator(fetch_forecast())
runner.run_until(handle, timeout_ms=30_000)
```

The request advances between LED blinks and MQTT keepalives.  A slow server or a stalled TLS handshake (TLS is the encryption behind https) doesn't take the device down with it, and the timeout is an argument, not an architecture.  The runnable version of this file, WiFi wiring included, ships in the requests library's `examples/` folder.

### Why generators and not async/await?

Two questions hide in that one, and they have separate answers.

**Who owns the loop?**  You do.  `runner.tick()` is a call you make from a `while True` you wrote, which is what lets a ChuMicro service sit beside code that knows nothing about ChuMicro and lets you decide what happens between turns.  An asyncio program is arranged the other way up: its event loop owns the `while True` and your code lives inside it.

**How is a pause spelled?**  As `yield from`, which is the same machinery `await` is built from.  MicroPython compiles `await x` into one `YIELD_FROM` bytecode, the same one `yield from x` produces.  Writing that directly buys three things:

- **You can see and stop at every pause.**  Set a breakpoint on the `yield from` line.  When a board misbehaves on your bench, the serial traceback names the line it was waiting on.  The runner gives services their turn in the order you registered them, so the sequence you read in your source is the sequence the device runs.
- **A pause is always a real pause.**  `yield from` a plain function and Python raises `TypeError` right there, so every `yield from` you write marks a genuine handoff: a place where the LED gets to blink and the MQTT keepalive gets its turn.  Ordinary helpers stay ordinary functions.
- **The device pays less.**  CircuitPython compiles each `await` into a method call that builds a fresh object every time the line resumes, which in a receive loop means one allocation per pass on a board whose heap is measured in kilobytes.  `yield from` is a single bytecode on both device runtimes, ChuMicro reuses the wait objects it yields, and the runner's tests hold its wait path to zero steady-state allocation.

Most services never reach for a generator at all.  A WiFi supervisor, an MQTT keepalive, a button debounce: each one answers "is there work?" and then does one piece of it, which reads clearly as the pair of methods the runner calls.  Generators are for the flows that genuinely run in sequence.

The full case, with both runtimes' compiler sources cited line by line, is [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md).

## A real project on one page

Put the pieces together and you get a real project.  This one is a greenhouse fan controller: it reports the temperature every five seconds, listens for fan-speed commands, and keeps its status LED blinking through it all.

```python
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="home-wifi", password="…"))
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "10.0.0.5", "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)
mqtt.subscribe("greenhouse/fan/set")
mqtt.connect()                       # keeps retrying until the broker answers

def publish_temperature(now):
    mqtt.publish("greenhouse/temperature", f"{read_celsius():.1f}".encode())

def follow_fan_commands():
    while True:
        message = yield from mqtt.next_message()   # wait for a command; the LED keeps blinking
        if message is None:
            return
        speed = max(0, min(100, int(message.payload.decode())))
        set_fan_duty(speed / 100)

runner = Runner()
runner.add(wifi)                     # brings WiFi up, reconnects when it drops
runner.add(mqtt)
runner.add_periodic(publish_temperature, period_ms=5_000)
runner.add_periodic(toggle_led, period_ms=500)     # the blink from the first example
runner.add_generator(follow_fan_commands())

while True:
    now = runner.tick()
    runner.wait(now)
```

Now do the worst thing you can do to a connected board: pull your router's plug.  The LED keeps blinking and the fan holds its speed while the board quietly retries.  Plug the router back in and the temperature starts flowing again on its own: the wifi service and the mqtt client handle the reconnecting, the re-subscribing, and the catching up for you.  Your part stays small and reads like a story: wait for a command, set the fan, wait for the next one, with `yield from` marking each place your code waits its turn.

[`demos/mqtt_sensor_motor`](demos/mqtt_sensor_motor/) is the runnable version, sensor and fan wiring written out for Pico W and ESP32: one command puts it on your board while your laptop plays the broker.  And when you're ready to build your own, the [workspace template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) starts you off with a project just like it.

## The engineering underneath

Claims about embedded software are cheap, so this project keeps receipts:

- Every library has a flash-size ceiling in CI.  A change that outgrows its budget fails the build and needs a measured justification to raise it.
- Hot paths carry zero-allocation contracts, tested on the device runtimes with the garbage collector disabled, because on a small heap the killer isn't peak memory, it's fragmentation and churn.
- Limits are measured, not guessed.  Recursion guards are set by probing the worst supported board until it faults, then backing off; deadlines and buffer sizes trace to bench numbers.
- Every non-obvious choice has a written [decision record](plans/decisions/): what was decided, what the alternatives were, and the evidence.  Over a hundred of them, and they get revisited when the facts change.
- When something fails on your bench, the tools classify the failure and name the fix (drive not mounted, board in bootloader mode, port held by another process) instead of leaving you a stack trace.

## Bring your own socket and clock

Every library takes its I/O and its clock as constructor arguments.  A socket needs four methods (`recv_into`, `send`, `close`, `setblocking`) and a clock needs three (`ticks_ms`, `ticks_add`, `ticks_diff`).  Anything with those methods is accepted: a stdlib socket, a wrapper from another library, or something you wrote this afternoon.  That one seam pays off twice.

**On your laptop, hand in a fake.**  Your tests run in milliseconds with nothing plugged in.  Every library with hardware-shaped dependencies ships its fakes in a `testing` module (`from chumicro_timing.testing import FakeTicks`), so your tests use the same tools the project's own tests do.  The same suite also runs under desktop builds of MicroPython and CircuitPython, which catches "works on my laptop, breaks on the board" before any code reaches hardware.  If you've ever debugged a library by adding prints and re-copying files to a USB drive, this is the part of ChuMicro you'll thank yourself for.

**In someone else's project, hand in what it already has.**  `import chumicro_mqtt` loads zero other ChuMicro modules, and supplying your own transport and clock keeps that closure empty, so the MQTT client can go into a codebase built on something else entirely and run from the loop that codebase already has:

```python
mqtt.connect()                      # non-blocking; no I/O happens here

while True:
    now = ticks.ticks_ms()
    if mqtt.check(now):             # does the client want a turn?
        mqtt.handle(now)            # one chunk of connect, send, or recv
    # your own work ticks here too
```

[Standalone integration](docs/contributing/standalone-integration.md) is the full recipe, with the measured import closure for every library and a copy-paste host test.  Keeping these seams costs a few kilobytes of flash and one extra frame per connect, under 1% of a 264 KB board.

## Watch it work on real hardware

The fastest way to judge a library is to watch it complete a real exchange.  The [`demos/`](demos/) folder holds end-to-end scenarios where your board and your laptop play both sides (and one that runs entirely on your laptop, no board needed), each one a single command from a clone of this repo:

- **[`mqtt_sensor_motor`](demos/mqtt_sensor_motor/)**: the board publishes its temperature over MQTT and takes fan-speed commands back, dimming its LED to match.  Your laptop runs the broker and the controller.
- **[`http_server_roundtrip`](demos/http_server_roundtrip/)**: the board serves HTTP routes, the laptop discovers it and exercises them.
- **[`sockets_runner_connector`](demos/sockets_runner_connector/)**: the TCP echo written as a straight-line generator, next to a [twin demo](demos/sockets_runner_connector_explicit/) doing the same job as an explicit state machine, so you can compare the two styles line by line.
- **[`laptop_roundtrip`](demos/laptop_roundtrip/)**: no board at all.  An HTTP fetch, the server it talks to, and a blinking LED share one runner on your laptop, so you can watch the request finish without the blink ever pausing.

Running one takes the one-time workspace setup, then the demo's driver:

```bash
git clone https://github.com/ChuMicro/ChuMicro && cd ChuMicro
python3 scripts/prepare_workspace.py        # one-time: isolated Python env, everything installed
source .venv/bin/activate
chumicro-workspace add-device               # one-time: register the plugged-in board

python demos/mqtt_sensor_motor/driver.py    # deploys the board side, then drives the round trip
```

The driver deploys `app.py` to your board, runs the laptop side against it, and prints the exchange as it happens; `--help` on any driver lists its options.  The tooling does the bench work for you: it picks the port, ships the files with the libraries they need, bakes in your WiFi credentials, and tails the board's output, for every demo here and every example in every library.  Networked demos read WiFi credentials from a gitignored `secrets.toml` at the repo root ([wiring wifi credentials](docs/wiring-wifi-credentials.md)), and the MQTT demos expect the `mosquitto` broker on your PATH (`brew install mosquitto`, or your package manager's equivalent).  No board on your desk?  `cd demos/laptop_roundtrip && python app.py` runs with nothing plugged in.

Each demo's README says what you'll see and what it proves.  For single-library learning material, every library also ships an `examples/` folder that deploys to a board with one command ([below](#try-an-example-on-a-board)).

## Install

> **New to board Python?**  A brand-new board may have no CircuitPython or MicroPython on it yet, and the commands below assume one is already running.  Either works with ChuMicro (CircuitPython is the gentler start).  Skip ahead to [Try an example on a board](#try-an-example-on-a-board), which handles the firmware and gets an LED blinking in four commands.

Already have a project and want one library on your board?  Every library installs by name, on every runtime.  Swap in `chumicro-mqtt`, `chumicro-wifi`, or anything from the table below:

```bash
# CircuitPython, via the circup bundle manager
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_timing

# MicroPython, via mpremote (MicroPython's CLI tool) and mip (its package manager)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython, via pip
pip install chumicro-timing
```

These commands install from the **stable** channel.  Every merge publishes to a separate **experimental** channel first and reaches stable when a maintainer promotes it, so a library merged since the last promotion may exist only on experimental for a while.  [`INSTALL.md`](INSTALL.md) covers installing from experimental, pre-compiled `.mpy` packages for lower RAM use, and per-runtime notes.

## The libraries

Each library installs independently and pulls in as little as possible.  Install one for a sensor sketch, or combine a dozen for a connected device.

| Library | What it's for |
|---|---|
| **[timing](libraries/timing/)** | Timers and deadlines that never block.  "Every 5 seconds, read the sensor."  "No reply in 2 seconds, give up."  No `time.sleep()`. |
| **[runner](libraries/runner/)** | The scheduler.  Register your services, call `runner.tick()` in your loop, everyone gets a turn.  `runner.wait()` idles the CPU between events. |
| **[wifi](libraries/wifi/)** | One WiFi service for both device runtimes.  Connects, retries with backoff, reconnects on drop, and tells your app what changed. |
| **[requests](libraries/requests/)** | HTTP/1.1 client.  A slow server or a TLS handshake never freezes your loop. |
| **[http_server](libraries/http_server/)** | HTTP/1.1 server with a `@server.route` decorator.  TLS where the runtime supports it; the guide has the current map. |
| **[mqtt](libraries/mqtt/)** | MQTT 3.1.1 client with QoS 0 and 1, last will, retain, and TLS.  Stays connected while your loop does everything else. |
| **[websockets](libraries/websockets/)** | WebSocket client and server, plain and TLS.  Pairs with `http_server` on one device. |
| **[sockets](libraries/sockets/)** | TCP, TLS, and UDP that behave the same on all three runtimes.  Used underneath `requests`, `http_server`, `mqtt`, and `websockets`, and usable directly. |
| **[ntp](libraries/ntp/)** | Sets the board's clock from the network.  Close enough to UTC for TLS certificate checks and honest log timestamps. |
| **[config](libraries/config/)** | Typed runtime settings with one dotted-key convention (`wifi.ssid`, `mqtt.broker.host`) shared by every library. |
| **[kvstore](libraries/kvstore/)** | Small persistent storage for what must survive a reboot: boot counters, tokens, timestamps.  Picks the right backend for your board. |
| **[msgpack](libraries/msgpack/)** | Binary serialization, smaller than JSON for typical sensor payloads.  Compatible with the wider `msgpack` ecosystem. |
| **[compat](libraries/compat/)** | The few standard-library pieces the device runtimes don't ship, so one file of code can run everywhere. |

For a dependency graph and a "pick a library by problem" index, see [`libraries/README.md`](libraries/).

## Try an example on a board

Every library ships runnable examples, and this repository deploys any of them to a connected board.  Nothing to set up beyond a clone:

```bash
git clone https://github.com/ChuMicro/ChuMicro
cd ChuMicro
python3 scripts/prepare_workspace.py                  # one-time: creates an isolated Python env, installs everything
source .venv/bin/activate                             # puts the chumicro tools on your PATH
chumicro-workspace deploy-example timing rate_blink
```

(Already set up from [running a demo](#watch-it-work-on-real-hardware)?  Only the last command is new.)

The first deploy walks you through picking the board's serial port and detecting its runtime, then remembers the board.  `chumicro-workspace deploy-example --list` prints every library-and-example pair you can deploy.  Networked examples read your WiFi name and password from a gitignored `secrets.toml` at the repo root; [wiring wifi credentials](docs/wiring-wifi-credentials.md) covers the details.

If your board doesn't have CircuitPython or MicroPython on it yet, `chumicro-deploy flash-firmware` installs one first.  It handles both the UF2-drive style (Pico) and the esptool style (ESP32); `--help` covers the flags per method.

## Start a real project

When you move past trying examples, start from the **[workspace template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)**.  It's a clone-and-go repository where your source lives on your laptop under version control and deploys to the board on demand, instead of being edited live on a USB drive that corrupts when the cable wiggles.  Deploys write to flash and verify every file by checksum; while you iterate, you can flip a board to RAM-mode deploys, which write nothing to flash at all.  Your WiFi password lives in a gitignored `secrets.toml` and gets baked onto the board at deploy time, so credentials never sit in your code or your git history.  And the same `pytest` that tests on your laptop tests on the board.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace && rm -rf .git && git init      # make its history yours
python3 run.py setup                            # creates a venv, installs everything
python3 run.py bootstrap                        # register your board, ship the starter demo
```

Its README walks through the reference project, a WiFi-to-MQTT sensor node with a persistent boot counter, and the multi-board flow.

## Testing

Every library is tested at four levels: plain `pytest` on your laptop, the same tests under desktop builds of MicroPython and CircuitPython, functional tests that run on a real connected board, and examples exercised on physical hardware before each release.  All of it runs through plain `pytest`, and that includes the hardware: click the play button next to a functional test in your IDE and it stages onto the plugged-in board, runs in the board's own Python, and reports back like any other test.

```bash
pytest libraries/timing/tests                            # laptop unit tests
pytest libraries/ --target unix-port --runtime both      # device runtimes, no device needed
pytest libraries/timing/functional_tests                 # on a real connected board
python scripts/run.py preflight                          # everything CI checks, locally
```

[CONTRIBUTING.md](CONTRIBUTING.md#testing) covers the details, including hardware setup for on-device runs.

## Bench tools

Command-line tools that run on your laptop, not the board.  They're what make the hardware workflow here one command per job: flash firmware, push code, read the board's output, run tests on the silicon.  And they stand on their own: they work against any CircuitPython or MicroPython board, whether or not your code uses the chumicro libraries.

| Tool | What it does |
|---|---|
| **[chumicro-workspace](workbench/workspace/)** | The tool you reach for first: scaffold projects, install firmware, deploy code, open a REPL, register boards, run checks. |
| **[chumicro-deploy](workbench/deploy/)** | Low-level board operations: probe what's running, push files, flash firmware, and fail with messages that say what to actually do. |
| **[chumicro-repl](workbench/repl/)** | Serial REPL and output tailing with readable tracebacks.  Scriptable from Python when a tool or test needs to drive a board. |
| **[chumicro-pytest-device](workbench/pytest-device/)** | The pytest plugin that stages tests onto a connected board and reports results back like any other test run. |

## Bring an AI coding agent

This repository is built so an agent can actually drive it.  The CLIs answer the questions an agent needs answered (`chumicro-deploy probe` reports what runtime and version a board is running), and when something fails, the tools classify the failure into a message that names the fix (drive not mounted, board in bootloader mode, port held by another process) instead of leaving a bare stack trace to guess at.

The practical effect: you can plug in a board you know nothing about and tell your agent "get this onto CircuitPython and blink an LED," and the agent has real commands for every step: probe the port, flash the right firmware, deploy an example, tail the serial output, and read back what happened.  [`AGENTS.md`](AGENTS.md) is the agent's operating manual for working in this repo; the [workspace template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) carries its own, plus step-by-step skill files for board registration, firmware, and deploy-and-debug.

## Documentation

📖 **[chumicro.github.io/ChuMicro](https://chumicro.com/ChuMicro/)**: hosted guides and API reference for every library, with a version selector for stable and experimental.

When something fails on your bench, [`docs/troubleshooting/`](docs/troubleshooting/) starts from the symptom (board not found, deploy wiped my files, WiFi won't connect, TLS errors, out of memory) and walks to the fix.

## Contributing

Issues, bug reports, and pull requests are welcome.  So is "I ran it on this board and here's what happened," which is some of the most useful feedback a hardware project can get.  Start with [`CONTRIBUTING.md`](CONTRIBUTING.md); if you're working with an AI coding agent, see [`AGENTS.md`](AGENTS.md).

A map of the repository, if you've cloned it and want to look around:

```text
libraries/    the libraries that run on boards (and your laptop)
workbench/    the host-side CLI tools
demos/        end-to-end scenarios: board + laptop, one command
support/      the cross-runtime test harness and shared doc assets
docs/         contributor guides and troubleshooting
plans/        design decision records and the maintainer's working notes
scripts/      developer task runner (run.py, tasks in run_tasks/)
```

## License

[MIT](LICENSE)
