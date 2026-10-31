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

ChuMicro is for people who program microcontroller boards in Python: a Raspberry Pi Pico W, an ESP32, an Adafruit Feather.  It gives those boards libraries for timers, buttons, knobs, WiFi, MQTT, HTTP, WebSockets, and storage that survives a reboot, all written to share one `while True:` loop, each taking a small step per pass.  The same code runs on CircuitPython, on MicroPython, and on the Python on your laptop.

## What's here

- **Libraries** ([`libraries/`](libraries/)) are small Python packages that run on your board.  Each one installs by itself with `circup`, `mip`, or `pip`, so a project that needs a timer gets a timer and nothing else.  This is what most people come for.
- **Laptop tools** ([`workbench/`](workbench/)) are command-line programs you run on your computer.  They install firmware, copy your code and the libraries it needs onto a board, and show you what the board prints.  They work with any CircuitPython or MicroPython board, whether or not your code uses the libraries.
- **The workbench template** ([its own repo](https://github.com/ChuMicro/ChuMicro-Workbench-Template)) is a ready-made folder for your own projects, already set up to use the tools.  Copy it when you start building something of your own.

This repository is where the libraries and tools are built.  It also holds a runnable example for every library and a set of end-to-end [demos](#demos).

## Pick your path

| I want to | Start at |
|---|---|
| Understand how the libraries work | [Three steps, one idea each](#three-steps-one-idea-each), right below |
| Make a board blink with a ready-made example | [Try an example on a board](#try-an-example-on-a-board) |
| Add one library to code I already have | [Install a library](#install-a-library) |
| Start a project of my own | [Start your own project](#start-your-own-project) |
| Carry my Arduino or Adafruit Learn habits over | [Coming from Arduino](docs/coming-from-arduino.md) |
| Fix a board that misbehaves | [Troubleshooting](docs/troubleshooting/) |
| Work on ChuMicro itself | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Three steps, one idea each

Most board code waits.  `time.sleep(1)` stops the whole board for a second, and a network request stops it until the server answers.  While the board waits, the LED stops blinking and the button stops answering.  ChuMicro libraries work in small steps instead: each one does a little of its job every time your loop comes round, then hands control straight back.

The examples below are CircuitPython.  On MicroPython only the LED and pin lines change, and the [timing](libraries/timing/examples/) and [buttons](libraries/buttons/examples/) examples show both versions.

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

`Rate` answers "is it time yet?"  The loop never pauses, so anything else you put in it gets a turn on every pass.  To run it, [install `chumicro_timing`](#install-a-library) and save the file as `code.py` on your CIRCUITPY drive.

### 2. Two things in one loop

Add a button wired between pin `GP14` and `GND` (a Pico W pin name; use any free pin on your board).  Pressing it pauses the blink:

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
    button.check(now)               # read the button; this never waits

    if button.just_pressed:         # true on the one pass where the press landed
        blinking = not blinking

    if blinking and blink.due(now):
        led.value = not led.value
```

The second job is one more `if` in the same loop.  With a `time.sleep(0.5)` in there, every press would wait up to half a second to be noticed.  Here the blink stops the moment you press.

### 3. Add WiFi and keep blinking

WiFi takes seconds to join and can drop at any moment, so it needs a turn on every pass, forever.  ChuMicro packages a job like that as a *service*: an object with a `check(now)` method that answers "do you have work to do?" and a `handle(now)` method that does one small piece of it.  A `Runner` holds your services and timers.  Each `runner.tick()` gives every one of them its turn, and `runner.wait(now)` lets the CPU rest until the next one is due.

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

Unplug your router while this runs.  The report says it is waiting, the WiFi service keeps retrying, and when the router comes back the board rejoins without you doing anything.  On MicroPython the LED blinks straight through all of it.  CircuitPython's firmware makes each connect attempt wait (up to 15 seconds, set by `connect_timeout_ms` in `WifiConfig`), so there the blink pauses during an attempt and resumes between them.  Opening a connection to a server has similar waits on both runtimes; [Does anything ever block?](docs/faq.md#does-anything-ever-block) lists them.

From here the same loop takes more services.  [`generator_fetch.py`](libraries/requests/examples/generator_fetch.py) fetches a web page every 30 seconds, written as one top-to-bottom function, and the [`mqtt_sensor_motor`](demos/mqtt_sensor_motor/) demo is a whole sensor-and-fan project talking MQTT.

## Install a library

Your board needs CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  If it has neither, install one from [circuitpython.org/downloads](https://circuitpython.org/downloads) or [micropython.org/download](https://micropython.org/download/) by following the steps on your board's page.

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

Then put your program on the board the way you already do: save it as `code.py` on the CIRCUITPY drive, or copy it to a MicroPython board with `mpremote cp blink.py :main.py` and press reset.  [The install guide](docs/install.md) covers the experimental channel, pre-compiled packages that use less RAM, and fixes for install errors.

## Try an example on a board

A clone of this repository puts any library's example on a connected board with one command:

```bash
git clone https://github.com/ChuMicro/ChuMicro
cd ChuMicro
python3 scripts/prepare_workspace.py      # once: creates .venv and installs the tools and libraries
source .venv/bin/activate                 # puts the chumicro commands on your PATH
chumicro-workspace deploy-example timing circuitpython_blink
```

`deploy-example` copies the example and the libraries it imports onto your board, restarts it, and shows you what it prints.  The first run asks which serial port the board is on, works out whether it runs CircuitPython or MicroPython, and remembers it.  On a MicroPython board, deploy `micropython_blink` and check the LED pin at the top of that file.

`chumicro-workspace deploy-example --list` prints every example.  The networked ones read your WiFi name and password from `secrets.toml` at the repository root, which git ignores; [Wiring WiFi credentials](docs/wiring-wifi-credentials.md) shows the format.

## Start your own project

Copy the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) and build in that.  Your code lives on your laptop under version control, and one command (a *deploy*) copies it and the libraries it needs onto the board, so nothing is lost when a USB cable wiggles mid-save.  Your WiFi password stays in a `secrets.toml` that git ignores and reaches the board only at deploy time.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace && rm -rf .git && git init      # make its history yours
python3 run.py setup                            # creates a venv and installs the tools
python3 run.py bootstrap --demo                 # registers your board and sends it a hello-world
```

[Start here](docs/start-here.md) walks the whole path, from a board still in its packaging to your own code running on it.

## The libraries

Each library installs independently and pulls in as little as possible.  Install one for a sensor sketch, or combine a dozen for a connected device.

| Library | What it's for |
|---|---|
| **[timing](libraries/timing/)** | Timers and deadlines that never block.  "Every 5 seconds, read the sensor."  "No reply in 2 seconds, give up."  No `time.sleep()`. |
| **[runner](libraries/runner/)** | The scheduler.  Register your services, call `runner.tick()` in your loop, everyone gets a turn.  `runner.wait()` idles the CPU between events. |
| **[buttons](libraries/buttons/)** | Buttons, switches, and key matrices.  A press lands even when your loop is busy, and debouncing, long presses, auto-repeat, and click counting come with it. |
| **[knobs](libraries/knobs/)** | Rotary encoders and analog knobs, read as a number that holds still.  A fast spin arrives whole; a parked wiper stops jittering. |
| **[wifi](libraries/wifi/)** | One WiFi service for both device runtimes.  Connects, retries with backoff, reconnects on drop, and tells your app what changed. |
| **[requests](libraries/requests/)** | HTTP/1.1 client.  Once the connection is open, a slow server never freezes your loop. |
| **[http_server](libraries/http_server/)** | HTTP/1.1 server with a `@server.route` decorator.  TLS where the runtime supports it; the guide has the current map. |
| **[mqtt](libraries/mqtt/)** | MQTT 3.1.1 client with QoS 0 and 1, last will, retain, and TLS.  Stays connected while your loop does everything else. |
| **[websockets](libraries/websockets/)** | WebSocket client and server, plain and TLS.  Pairs with `http_server` on one device. |
| **[sockets](libraries/sockets/)** | TCP, TLS, and UDP that behave the same on all three runtimes.  Used underneath `requests`, `http_server`, `mqtt`, and `websockets`, and usable directly. |
| **[ntp](libraries/ntp/)** | Gets the current time from a network time server.  Close enough to UTC for TLS certificate checks and honest log timestamps. |
| **[config](libraries/config/)** | Typed runtime settings with one dotted-key convention (`wifi.ssid`, `mqtt.broker.host`) shared by every library. |
| **[kvstore](libraries/kvstore/)** | Small persistent storage for what must survive a reboot: boot counters, tokens, timestamps.  Picks the right backend for your board. |
| **[msgpack](libraries/msgpack/)** | Binary serialization, smaller than JSON for typical sensor payloads.  Compatible with the wider `msgpack` ecosystem. |
| **[compat](libraries/compat/)** | The few standard-library pieces the device runtimes don't ship, so one file of code can run everywhere. |

[`libraries/README.md`](libraries/) says when to reach for each one and draws how they depend on each other.

## Demos

Each demo is a small project where your board and your laptop play both sides of a real exchange, run with one command from a clone of this repo.

- **[`mqtt_sensor_motor`](demos/mqtt_sensor_motor/)**: the board publishes its temperature over MQTT and takes fan-speed commands back, lighting its LED while the fan runs.  Your laptop runs the broker and the controller.
- **[`press_through_fetch`](demos/press_through_fetch/)**: the board fetches a page from your laptop every three seconds while you press a button whenever you like.  Every press is reported, mid-fetch included.
- **[`http_server_roundtrip`](demos/http_server_roundtrip/)**: the board serves web pages, and your laptop finds it on the network and calls them.
- **[`laptop_roundtrip`](demos/laptop_roundtrip/)**: no board needed.  A web request, the server it talks to, and a blinking LED share one loop on your laptop, so you can watch the request finish without the blink ever pausing.

After the one-time setup in [Try an example on a board](#try-an-example-on-a-board), run a demo's driver, for example `python demos/mqtt_sensor_motor/driver.py`.  Each demo's README says what to wire, what you will see, and what it needs (the MQTT demos need the `mosquitto` broker installed).  [`demos/`](demos/) lists them all.

## Laptop tools

| Tool | What it does |
|---|---|
| **[chumicro-workspace](workbench/workspace/)** | The one you reach for first: register boards, install firmware, deploy code, open a REPL, scaffold projects, run checks. |
| **[chumicro-deploy](workbench/deploy/)** | Lower-level board operations: probe what's running, push files, flash firmware, and fail with messages that say what to do next. |
| **[chumicro-repl](workbench/repl/)** | Serial REPL and output tailing with readable tracebacks.  Scriptable from Python when a tool or test needs to drive a board. |
| **[chumicro-pytest-device](workbench/pytest-device/)** | The pytest plugin that runs tests on a connected board and reports the results like any other test run. |

## Going deeper

- **Why generators and not `async`/`await`?**  [Does this use async and await?](docs/faq.md#does-this-use-async-and-await) answers it in a paragraph; [Decision 0087](plans/decisions/0087-generators-for-sequential-io.md) makes the full case, compiler sources included.
- **Using one library inside a project that isn't built on ChuMicro.**  Every library takes its socket and its clock as arguments, so it runs from a loop you already have.  [Standalone integration](docs/contributing/standalone-integration.md) is the recipe.
- **How the libraries are kept honest.**  Each one runs its tests on your laptop's Python and on desktop builds of MicroPython and CircuitPython, carries a flash-size ceiling that CI enforces, and runs on real boards before release.  [CONTRIBUTING.md](CONTRIBUTING.md#testing) shows how to run the same tests.
- **Why things are the way they are.**  Every non-obvious choice has a [decision record](plans/decisions/) with the alternatives and the evidence.
- **Working with an AI coding agent.**  The tools give an agent a command for every step (probe a board, flash firmware, deploy, read the output), and [`AGENTS.md`](AGENTS.md) is its manual for this repo.
- **Hosted documentation.**  [chumicro.com/ChuMicro](https://chumicro.com/ChuMicro/) has a guide and API reference for every library, plus the [Questions people ask](docs/faq.md) page.

## Contributing

Issues, bug reports, and pull requests are welcome.  So is "I ran it on this board and here's what happened," which is some of the most useful feedback a hardware project gets.  Start with [`CONTRIBUTING.md`](CONTRIBUTING.md).

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
