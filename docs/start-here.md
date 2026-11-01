---
title: "Start here: from a new board to your code running on it"
---

# Start here

Every command on this page runs in a terminal on your laptop.

You need:

- A board, such as a Raspberry Pi Pico W or an ESP32 development board.
- A USB cable that carries data as well as power.  A charge-only cable leaves the board invisible to your laptop.
- Python 3.11 or newer on your laptop.

[Coming from Arduino](coming-from-arduino.md) maps Arduino's `setup()` and `loop()`, and the `time.sleep()` of Adafruit Learn guides, onto the code below.  [Glossary](glossary.md) defines the ChuMicro words on this page, such as *deploy* and `devices.yml`.

## 1. Put CircuitPython or MicroPython on the board

ChuMicro runs on CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  If your board already runs one of those, skip to step 2.

Install the runtime from its own site:

- **CircuitPython**: find your board at [circuitpython.org/downloads](https://circuitpython.org/downloads).  A Pico W takes a `.uf2` file.  Hold the BOOTSEL button while you plug the board in, then drag the file onto the `RPI-RP2` drive that appears.  Many ESP32 boards have an **Open Installer** button on their page that flashes the board from your browser.
- **MicroPython**: find your board at [micropython.org/download](https://micropython.org/download/) and follow the steps on its page.

Either runtime works.  Code written for one runs on the other once its pin lines change.  [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md) covers boards that will not take a flash.

## 2. Get the workbench

The [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) is a folder for your board projects.  Its `run.py` keeps track of your boards, copies code onto them, and runs your tests.

For a copy on GitHub, press **Use this template** on the template's page and clone your new repository.  For a copy on your laptop only, clone the template and start a fresh history:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
rm -rf .git && git init          # the history is yours from here
```

Then install the tools from inside the folder:

```bash
python3 run.py setup             # creates a virtual environment and installs the tools
```

`setup` builds a virtual environment in `my-workspace/.venv`: a private Python with the tools installed in it.  `run.py` switches into it on every command, so `python3 run.py <command>` works from a fresh terminal with nothing to activate.  `setup` also creates `secrets.toml` and `devices.yml`, two files git ignores.

## 3. Register the board

Plug the board in and run:

```bash
python3 run.py bootstrap
```

`bootstrap` finds the board's serial port and works out whether the board runs CircuitPython or MicroPython.  It records both in `devices.yml`.  When the laptop sees several serial ports, `bootstrap` asks which one is the board.  From then on, every command uses that board unless you name another with `--device`.

[Board not found](troubleshooting/board-not-found.md) covers a board that does not appear.  [CIRCUITPY on macOS](troubleshooting/macos-circuitpy.md) covers a CIRCUITPY drive that will not mount on a Mac.

## 4. Write a blink and send it over

Create a project and fetch the timing library it uses:

```bash
python3 run.py new blinker                    # creates projects/blinker/
python3 run.py library add chumicro_timing    # fetches the library into the workspace
```

Open `projects/blinker/app.py` and replace everything in it with this:

```python
import board
import digitalio
from chumicro_timing import Rate, ticks_ms


def run():
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    blink = Rate(500, ticks_ms())       # due every 500 ms
    print("blinker: running")

    while True:                         # set up once, then loop until the power goes
        now = ticks_ms()
        if blink.due(now):              # is it time yet?
            led.value = not led.value
            print("blink")
```

The deploy below writes a three-line `code.py` on CircuitPython, or `main.py` on MicroPython, that calls `run()` when the board starts.  Your program goes inside `run()`: setup first, then a `while True:` loop that never ends.  The loop has no `time.sleep()` in it.  `blink.due(now)` answers "is it time yet?" and returns straight away.  Anything you add to the loop later gets a turn on every pass.

That code is CircuitPython.  On MicroPython, change the LED lines:

- Replace `import board` and `import digitalio` with `from machine import Pin`.
- Build the LED with `led = Pin("LED", Pin.OUT)` on a Pico W, or `led = Pin(2, Pin.OUT)` on many ESP32 boards.
- Flip it with `led.value(not led.value())`.

Send the project to the board and watch what it prints:

```bash
python3 run.py deploy blinker --tail 30     # copy it over, then show the output for 30 seconds
```

The LED blinks.  The terminal prints `blink` twice a second.  `deploy` copies your project and every library it imports onto the board, then restarts the board.  Your files stay on your laptop under version control, so a cable that comes loose mid-copy costs one more run of `deploy`.

To see the output again later, or to type at the board's Python prompt:

```bash
python3 run.py repl --tail 30    # show the board's output for 30 seconds
python3 run.py repl              # an interactive prompt on the board
```

[Three steps, one idea each](https://github.com/ChuMicro/ChuMicro#three-steps-one-idea-each) adds a button and then WiFi to this same loop.

## 5. Put the board on your WiFi

Network projects read your WiFi name and password from `secrets.toml` in the workspace folder.  `setup` created that file with placeholder values.  Replace them with your own:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

The template's `examples/wifi_only` joins your network and prints its status every five seconds.  Copy it into a project of your own, fetch the libraries it imports, and deploy it:

```bash
python3 run.py new my_wifi --from examples/wifi_only
python3 run.py library add chumicro_runner
python3 run.py library add chumicro_wifi
python3 run.py deploy my_wifi --tail 30
```

The board prints `wifi: connecting` until it joins.  Then it prints `wifi: connected at` followed by its address.  Unplug your router, and the board prints `wifi: reconnecting`.  Plug the router back in, and the board rejoins on its own.  [Wiring WiFi credentials](wiring-wifi-credentials.md) shows how the password reaches the board, adds MQTT broker settings to the same file, and lists every key the libraries read.

## Where to go next

- [Build a WiFi temperature sensor](tutorial-wifi-sensor.md) grows a blink, one step at a time, into a board that publishes its temperature over MQTT.
- [How it works](how-it-works.md) builds from a plain `while True:` loop up to a runner and a deploy.
- The template's `examples/` folder holds more projects to copy the same way: `periodic_get` for a timed web request, `telemetry_publisher` for MQTT readings, and `two_board_handshake` for two boards talking over HTTP.  `python3 run.py new <name> --from examples/<example>` copies one into `projects/`.  The template's README walks through a full sensor project.
- [Questions people ask](faq.md): why a board freezes on the network, whether these libraries use async, what they cost in flash, and how to test without hardware.
- [The library reference](https://chumicro.com/ChuMicro/): every library, with its own guide and API pages.
- [Troubleshooting](troubleshooting/README.md): pages organized by the symptom on your screen.
- Newer firmware later on: `python3 run.py install-firmware --method uf2` on a Pico, or `--method esptool` on an ESP32, flashes the latest stable release onto the registered board.
