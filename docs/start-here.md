---
title: "Start here: from a new board to your code running on it"
---

# Start here

This page takes a board still in its packaging to a program of your own blinking its LED, and then to that board on your WiFi.  Every command runs on your laptop.

You need:

- a board, such as a Raspberry Pi Pico W or an ESP32 development board;
- a USB cable that carries data as well as power (a charge-only cable is the most common reason a board never shows up);
- Python 3.11 or newer on your laptop.

Coming from Arduino sketches or Adafruit Learn guides?  [Coming from Arduino](coming-from-arduino.md) shows how `setup()`, `loop()`, and `time.sleep()` map onto the code below.

## 1. Put CircuitPython or MicroPython on the board

ChuMicro runs on CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  If your board already runs one of those, skip to step 2.

Install a runtime the way its own guides do:

- **CircuitPython**: find your board at [circuitpython.org/downloads](https://circuitpython.org/downloads).  A Pico W takes a `.uf2` file: hold the BOOTSEL button while you plug the board in, then drag the file onto the `RPI-RP2` drive that appears.  Many ESP32 boards have an **Open Installer** button on their page that flashes the board from your browser.
- **MicroPython**: find your board at [micropython.org/download](https://micropython.org/download/) and follow the steps on its page.

Either runtime works, and the code you write for one runs on the other with only the pin lines changed.  [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md) covers boards that will not take a flash.

## 2. Get the workbench

The [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) is a folder for your board projects.  It holds your code, keeps track of your boards, copies code onto them, and runs your tests.  Press **Use this template** on that page to make your own copy on GitHub and clone it, or clone it straight down and start a fresh history:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
rm -rf .git && git init          # the history is yours from here
python3 run.py setup             # creates a virtual environment and installs the tools
```

`setup` builds a virtual environment, a private copy of Python and the tools that lives inside `my-workspace/`.  `run.py` switches into it on every command, so `python3 run.py <command>` works from a fresh terminal with nothing to activate.

## 3. Register the board

Plug the board in and run:

```bash
python3 run.py bootstrap
```

`bootstrap` finds the board's serial port, works out whether it runs CircuitPython or MicroPython, and records it in `devices.yml`.  From then on, every command uses that board unless you name another with `--device`.

Two things that go wrong here have their own pages: [the board does not appear](troubleshooting/board-not-found.md), and on a Mac, [CIRCUITPY not mounting](troubleshooting/macos-circuitpy.md).

## 4. Write a blink and send it over

Make a project, and fetch the timing library it will use:

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

When the board starts, the workbench calls your `run()` function, so your program goes inside it: setup first, then a `while True:` loop that never ends.  The loop has no `time.sleep()` in it.  `Rate` answers "is it time yet?" and the loop goes round again either way, so anything you add later gets a turn on every pass.

That code is CircuitPython.  On MicroPython, swap `import board` and `import digitalio` for `from machine import Pin`, set the LED up in one line with `led = Pin("LED", Pin.OUT)` on a Pico W or `led = Pin(2, Pin.OUT)` on most ESP32 boards, and flip it with `led.value(not led.value())`.

Send it to the board and watch what it prints:

```bash
python3 run.py deploy blinker --tail 30     # copy it over, then show the output for 30 seconds
```

The LED blinks and the terminal prints `blink` twice a second.  `deploy` copies your project and every library it imports onto the board, checks that each file arrived intact, and restarts the board.  The original stays on your laptop under version control, so a cable that comes loose mid-copy costs you a re-run, not your work.

To see the output again later, or to type at the board's Python prompt:

```bash
python3 run.py repl --tail 30    # show the board's output for 30 seconds
python3 run.py repl              # an interactive prompt on the board
```

[Three steps, one idea each](https://github.com/ChuMicro/ChuMicro#three-steps-one-idea-each) adds a button and then WiFi to this same loop.

## 5. Put the board on your WiFi

Network projects read your WiFi name and password from `secrets.toml` in the workspace folder.  Git ignores that file, and each deploy copies the values onto the board, so your password stays out of your code and your git history:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

The template ships a WiFi example that joins your network and prints its status every five seconds, forever.  Copy it into a project of your own, fetch the libraries it uses, and deploy it:

```bash
python3 run.py new my_wifi --from examples/wifi_only
python3 run.py library add chumicro_runner
python3 run.py library add chumicro_wifi
python3 run.py deploy my_wifi --tail 30
```

The board prints `wifi: connecting` until it joins, then `wifi: connected at` and its address.  Unplug your router and it prints `wifi: reconnecting`; plug it back in and the board rejoins on its own.  [Wiring WiFi credentials](wiring-wifi-credentials.md) adds MQTT broker settings to the same file and lists every key the libraries read.

## Where to go next

- The template's `examples/` folder holds more projects to copy the same way: a periodic web request, MQTT telemetry, and two boards talking to each other.  `python3 run.py new <name> --from examples/<example>` copies one into `projects/`, and the template's README walks a full sensor project.
- [Questions people ask](faq.md): why a board freezes on the network, whether these libraries use async, what they cost in flash, and how to test without hardware.
- [The library reference](https://chumicro.com/ChuMicro/): every library, with its own guide and API pages.
- [Troubleshooting](troubleshooting/README.md): keyed to the symptom you are looking at.
- Newer firmware later on: `python3 run.py install-firmware --method uf2` on a Pico, or `--method esptool` on an ESP32, flashes the latest stable release onto the registered board.
