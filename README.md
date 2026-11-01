<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Python libraries for CircuitPython and MicroPython boards, and the laptop tools that put your code on them.</big></strong>
</p>

<p align="center"><big>
  <a href="https://chumicro.com/ChuMicro/">Docs</a> •
  <a href="#pick-your-path">Get started</a> •
  <a href="docs/coming-from-arduino.md">Coming from Arduino</a> •
  <a href="#the-libraries">Libraries</a> •
  <a href="#demos">Demos</a> •
  <a href="CONTRIBUTING.md">Contributing</a>
</big></p>

---

ChuMicro is a set of Python libraries for microcontroller boards such as a Raspberry Pi Pico W, an ESP32, or an Adafruit Feather.  The libraries cover timers, buttons, knobs, WiFi, MQTT, HTTP, WebSockets, and storage that survives a reboot.  A library that waits on something, such as WiFi, a server, or a button, does its waiting inside your `while True:` loop.  It takes a small step on each pass and hands control straight back.  Every library runs on CircuitPython, on MicroPython, and on the Python on your laptop.

## What's here

- **Libraries** ([`libraries/`](libraries/)) are small Python packages that run on your board.  Each one installs by itself with `circup`, `mip`, or `pip`.  A project that needs a timer installs `chumicro_timing` and nothing else.
- **Laptop tools** ([`workbench/`](workbench/)) are command-line programs for your computer.  They install firmware, copy your code and the libraries it imports onto a board, and show what the board prints.  They work with any CircuitPython or MicroPython board, whether or not your code uses the libraries.
- **The workbench template** ([ChuMicro-Workbench-Template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)) is a folder for your own projects with the laptop tools already set up.  Copy it to start a project of your own.

This repository builds the libraries and the laptop tools.  It also holds a runnable example for every library and end-to-end [demos](#demos).

## Pick your path

| I want to | Start at |
|---|---|
| Understand how the libraries work | [Three steps, one idea each](#three-steps-one-idea-each), right below, then [How it works](docs/how-it-works.md) |
| Make a board blink with a ready-made example | [Try an example on a board](#try-an-example-on-a-board) |
| Build a WiFi temperature sensor, one step at a time | [Build a WiFi temperature sensor](docs/tutorial-wifi-sensor.md) |
| Add one library to code I already have | [Install a library](#install-a-library) |
| Start a project of my own | [Start your own project](#start-your-own-project) |
| Carry my Arduino or Adafruit Learn habits over | [Coming from Arduino](docs/coming-from-arduino.md) |
| Look up a word these pages use | [Glossary](docs/glossary.md) |
| Fix a board that misbehaves | [Troubleshooting](docs/troubleshooting/) |
| Work on ChuMicro itself | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Three steps, one idea each

Most board code waits.  `time.sleep(1)` stops the whole board for a second.  A network request stops it until the server answers.  While the board waits, the LED stops blinking and the button stops answering.  A ChuMicro library does a small piece of its job each time your loop comes round, then hands control straight back.

The examples below are CircuitPython.  On MicroPython, only the LED and pin lines change.  The [timing](libraries/timing/examples/) and [buttons](libraries/buttons/examples/) examples show both versions.

### 1. Blink without time.sleep()

```python
import board, digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
blink = Rate(500, ticks_ms())       # due every 500 ms

while True:
    now = ticks_ms()
    if blink.due(now):              # is it time yet?
        led.value = not led.value
```

`blink.due(now)` answers "is it time yet?" and returns straight away.  The loop never pauses, so anything else you add to it gets a turn on every pass.  To run it, [install `chumicro_timing`](#install-a-library) and save the file as `code.py` on your CIRCUITPY drive.

### 2. Two things in one loop

Wire a button between pin `GP14` and `GND`.  `GP14` is a pin name on a Pico W.  Any free pin on your board works in its place.  Pressing the button pauses the blink:

```python
import board, digitalio
from chumicro_buttons import Button
from chumicro_timing import Rate, ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
blink = Rate(500, ticks_ms())
button = Button(pin=board.GP14, ticks=ticks)
blinking = True

while True:
    now = ticks_ms()
    button.check(now)               # read the button without waiting

    if button.just_pressed:         # true on the one pass where the press landed
        blinking = not blinking

    if blinking and blink.due(now):
        led.value = not led.value
```

The second job is one more `if` in the same loop.  With a `time.sleep(0.5)` in the loop, a press would wait up to half a second before the code saw it.  Here the blink stops the moment you press.

### 3. Add WiFi and keep blinking

WiFi takes seconds to join and can drop at any moment.  The code that keeps it up needs a turn on every pass, forever.  ChuMicro packages a job like that as a [*service*](docs/glossary.md#service): an object with a `check(now)` method that answers "do you have work to do?" and a `handle(now)` method that does one small piece of it.  A `Runner` holds your services and timers.  Each `runner.tick()` gives every one of them its turn.  `runner.wait(now)` lets the CPU rest until the next one is due.

```python
import board, digitalio
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))

def blink(now):
    led.value = not led.value

def report(now):
    if wifi.connected:
        print("online at", wifi.ip)
    else:
        print("waiting for wifi")

runner = Runner()
runner.add(wifi)                                # joins, retries, rejoins after a drop
runner.add_periodic(blink, period_ms=500)
runner.add_periodic(report, period_ms=5_000)

while True:
    now = runner.tick()                         # every service and timer gets its turn
    runner.wait(now)                            # rest until the next one is due
```

Unplug your router while this runs.  The report prints `waiting for wifi` while the WiFi service keeps retrying.  When the router comes back, the board rejoins on its own.  On MicroPython, the LED blinks straight through the outage.  On CircuitPython, the blink pauses while each connect attempt runs.  [Does anything ever block?](docs/faq.md#does-anything-ever-block) lists that wait and the others.

The same loop takes more services.  [`generator_fetch.py`](libraries/requests/examples/generator_fetch.py) fetches a web page every 30 seconds from one top-to-bottom function.  [Build a WiFi temperature sensor](docs/tutorial-wifi-sensor.md) grows this loop, one step at a time, into a board that publishes its temperature over MQTT.

## Install a library

Your board needs CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  [Start here](docs/start-here.md#1-put-circuitpython-or-micropython-on-the-board) installs one on a board that has neither.

Every library installs by name.  Swap `timing` for any library in [the table below](#the-libraries):

```bash
# CircuitPython, with circup (Adafruit's library installer)
circup bundle-add ChuMicro/ChuMicro-Bundle    # once per computer
circup install chumicro_timing

# MicroPython, with mpremote (MicroPython's command-line tool)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# The Python on your laptop
pip install chumicro-timing
```

Save your program as `code.py` on the CIRCUITPY drive.  On MicroPython, copy it over with `mpremote cp blink.py :main.py` and press reset.  [Installing libraries](docs/install.md) covers the experimental channel, pre-compiled packages that use less RAM, and fixes for install errors.

## Try an example on a board

A clone of this repository puts any library's example on a connected board with one command:

```bash
git clone https://github.com/ChuMicro/ChuMicro
cd ChuMicro
python3 scripts/prepare_workspace.py      # once: creates .venv and installs the tools and libraries
source .venv/bin/activate                 # puts the chumicro commands on your PATH
chumicro-workspace deploy-example timing circuitpython_blink
```

`deploy-example` copies the example and the libraries it imports onto your board, restarts the board, and shows what it prints.  On the first run, it finds the board's serial port, works out whether the board runs CircuitPython or MicroPython, and records both in `devices.yml`.  A MicroPython board takes `micropython_blink`.  Check the LED pin at the top of that file before you deploy it.

`chumicro-workspace deploy-example --list` prints every example.  The networked examples read your WiFi name and password from `secrets.toml` at the repository root, a file git ignores.  [Wiring WiFi credentials](docs/wiring-wifi-credentials.md#running-an-example-from-a-clone-of-the-chumicro-repository) shows its format.

## Start your own project

Copy the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) and build there.  Your code stays on your laptop under version control.  A *deploy* copies it, the libraries it imports, and your settings onto the board.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace && rm -rf .git && git init      # make its history yours
python3 run.py setup                            # creates a venv and installs the tools
python3 run.py bootstrap --demo                 # registers your board and sends it a hello-world
```

[Start here](docs/start-here.md) walks the whole path, from a board still in its packaging to your own code running on it.

## The libraries

Each library installs on its own and brings along only the ChuMicro libraries it depends on.

| Library | What it's for |
|---|---|
| **[timing](libraries/timing/)** | Timers and deadlines that never block.  "Every 5 seconds, read the sensor."  "No reply in 2 seconds, give up."  No `time.sleep()`. |
| **[runner](libraries/runner/)** | The scheduler.  `runner.tick()` gives every registered service and timer its turn.  `runner.wait()` idles the CPU until the next one is due. |
| **[buttons](libraries/buttons/)** | Buttons, switches, and key matrices.  A press lands even while your loop is busy.  Debouncing, long presses, auto-repeat, and click counting are built in. |
| **[knobs](libraries/knobs/)** | Rotary encoders and analog knobs, read as a number that holds still.  A fast spin arrives whole.  A potentiometer left alone reads steady. |
| **[wifi](libraries/wifi/)** | One WiFi service for both board runtimes.  Connects, retries with backoff, reconnects after a drop, and tells your app what changed. |
| **[requests](libraries/requests/)** | HTTP/1.1 client.  Once the connection is open, a slow server never freezes your loop. |
| **[http_server](libraries/http_server/)** | HTTP/1.1 server with a `@server.route` decorator.  The guide lists which runtimes serve TLS. |
| **[mqtt](libraries/mqtt/)** | MQTT 3.1.1 client with QoS 0 and 1, last will, retain, and TLS.  Stays connected while your loop does everything else. |
| **[websockets](libraries/websockets/)** | WebSocket client and server, plain and TLS.  Shares a board with `http_server`. |
| **[sockets](libraries/sockets/)** | TCP, TLS, and UDP that behave the same on all three runtimes.  Used underneath `requests`, `http_server`, `mqtt`, and `websockets`, and usable directly. |
| **[ntp](libraries/ntp/)** | Gets the current time from a network time server.  Close enough to UTC for TLS certificate checks and honest log timestamps. |
| **[config](libraries/config/)** | Typed runtime settings with one dotted-key naming scheme (`wifi.ssid`, `mqtt.broker.host`) shared by every library. |
| **[kvstore](libraries/kvstore/)** | Small persistent storage for what must survive a reboot: boot counters, tokens, timestamps.  Picks the storage your board has. |
| **[msgpack](libraries/msgpack/)** | Binary serialization, smaller than JSON for typical sensor payloads.  Reads and writes the same bytes as PyPI's `msgpack`. |
| **[compat](libraries/compat/)** | Standard-library pieces the board runtimes lack, such as `functools.partial`, so one file of code runs on all three runtimes. |

[`libraries/README.md`](libraries/) says when to reach for each library and draws how they depend on each other.

## Demos

Each demo is a small project in which your board and your laptop talk to each other.  One command from a clone of this repository runs it.

- **[`mqtt_sensor_motor`](demos/mqtt_sensor_motor/)**: the board publishes its temperature over MQTT and takes fan-speed commands back.  Its LED lights while the fan runs.  Your laptop runs the broker and the controller.
- **[`press_through_fetch`](demos/press_through_fetch/)**: the board fetches a page from your laptop every three seconds while you press a button at any moment.  Every press is reported, mid-fetch included.
- **[`http_server_roundtrip`](demos/http_server_roundtrip/)**: the board serves web pages.  Your laptop finds it on the network and requests them.
- **[`laptop_roundtrip`](demos/laptop_roundtrip/)**: no board needed.  A web request, the server it talks to, and a blinking LED share one loop on your laptop.  The blink keeps going while the request runs.

After the one-time setup in [Try an example on a board](#try-an-example-on-a-board), run a demo's driver, such as `python demos/mqtt_sensor_motor/driver.py`.  [`demos/README.md`](demos/) lists every demo, simplest first, with what each one needs.

## Laptop tools

| Tool | What it does |
|---|---|
| **[chumicro-workspace](workbench/workspace/)** | Registers boards, installs firmware, deploys code, opens a REPL, scaffolds projects, and runs checks.  Most work goes through this command. |
| **[chumicro-deploy](workbench/deploy/)** | Lower-level board operations: probe what's running, push files, flash firmware.  Each failure message says what to do next. |
| **[chumicro-repl](workbench/repl/)** | Serial REPL and output tailing with readable tracebacks.  Scriptable from Python when a tool or test needs to drive a board. |
| **[chumicro-pytest-device](workbench/pytest-device/)** | A pytest plugin that runs tests on a connected board and reports each result as a normal test line. |

## Going deeper

- **Why generators and not `async`/`await`?**  [Does this use async and await?](docs/faq.md#does-this-use-async-and-await) gives the short answer.  [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md) makes the full case, compiler sources included.
- **One library inside a project built without ChuMicro.**  Every library takes its socket and its clock as arguments, so it runs from any existing loop.  [Standalone integration](docs/contributing/standalone-integration.md) is the recipe.
- **How the libraries are tested.**  Each library runs its tests on your laptop's Python and on desktop builds of MicroPython and CircuitPython.  CI holds each one under a flash-size ceiling.  Each one runs on real boards before release.  [CONTRIBUTING.md](CONTRIBUTING.md#testing) shows how to run the same tests.
- **Why ChuMicro is built this way.**  The [decision records](plans/decisions/) give each design choice with its alternatives and its evidence.
- **Working with an AI coding agent.**  The laptop tools give an agent a command for every step: probe a board, flash firmware, deploy, read the output.  [`AGENTS.md`](AGENTS.md) is the agent's manual for this repository.
- **Hosted documentation.**  [chumicro.com/ChuMicro](https://chumicro.com/ChuMicro/) has a guide and API reference for every library, plus the [Questions people ask](docs/faq.md) page.

## Contributing

Issues, bug reports, and pull requests are welcome.  So is a note that says "I ran it on this board, and here's what happened."  Start with [`CONTRIBUTING.md`](CONTRIBUTING.md).

```text
libraries/    the libraries that run on boards (and your laptop)
workbench/    the laptop tools
demos/        end-to-end projects: board and laptop, one command
support/      the cross-runtime test harness and shared doc assets
docs/         user guides, troubleshooting, and contributor guides
plans/        design decision records and the maintainers' working notes
scripts/      developer task runner (run.py, tasks in run_tasks/)
```

## License

[MIT](LICENSE)
