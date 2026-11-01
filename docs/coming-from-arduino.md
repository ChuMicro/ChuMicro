---
title: "Coming from Arduino: setup(), loop(), millis(), and while True with ChuMicro"
---

# Coming from Arduino

An Arduino sketch splits a program into `setup()` and `loop()`.  An Adafruit Learn guide ends `code.py` in a `while True:` loop with a `time.sleep()` inside.  ChuMicro keeps that loop.

The examples use CircuitPython's `board` and `digitalio`.  On MicroPython, only the pin lines change, as [On MicroPython](#on-micropython) shows.

## What stays the same

The board still runs Python, CircuitPython or MicroPython, from a `code.py` or a `main.py`.  Pins still come from your runtime's own `board` and `digitalio`, or from `machine.Pin`.  `print()` still writes to the serial console.  The program still ends in a `while True:` loop that runs until the power goes.

The code above `while True:` does the job of Arduino's `setup()`.  The body of the loop does the job of `loop()`.

## What changes: your code checks the clock instead of sleeping

`time.sleep(1)` and `delay(1000)` stop the whole board for a second.  A program that only blinks an LED loses nothing to that.  In a program with a button, a sensor, and WiFi, every sleep is a second in which the button goes unread and the network goes unanswered.

ChuMicro code checks the clock instead.  Each pass through the loop asks whether anything is due, does the work that is due, and moves on.  A ChuMicro program still sleeps in one place, `runner.wait()`, and only until the next job is due.  [Two things at once](#two-things-at-once-runner) shows it.

## Blink: `time.sleep()` becomes `Rate`

An Adafruit Learn blink:

```python
import time

import board
import digitalio

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

while True:
    led.value = not led.value
    time.sleep(0.5)
```

The same blink with `chumicro_timing`:

```python
import board
import digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

blink = Rate(500, ticks_ms())   # due once every 500 ms

while True:
    now = ticks_ms()
    if blink.due(now):
        led.value = not led.value
    # anything you add here runs on every pass, between blinks
```

`ticks_ms()` reads the clock in milliseconds, like Arduino's `millis()`.  `blink.due(now)` returns `True` once every 500 ms and `False` on every other pass.

`Rate` folds the `previousMillis` and `interval` of Arduino's BlinkWithoutDelay sketch into one object:

```cpp
unsigned long previousMillis = 0;
const long interval = 500;
int ledState = LOW;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;
    ledState = !ledState;
    digitalWrite(LED_BUILTIN, ledState);
  }
}
```

`Rate` also holds its schedule.  When a pass runs late, the next blink still lands on the 500 ms beat.  BlinkWithoutDelay counts again from the late moment and drifts.

`ticks_ms()` wraps back to zero about every 6.2 days.  `ticks_diff(now, then)` subtracts two tick values correctly across that [wraparound](glossary.md#wraparound), and `Rate` and `Deadline` call it for you.

## Buttons: debouncing becomes `chumicro_buttons`

A Learn guide reads the pin and sleeps 20 ms to ride out contact bounce, or uses `adafruit_debouncer`:

```python
import board
import digitalio
from adafruit_debouncer import Debouncer

pin = digitalio.DigitalInOut(board.GP14)
pin.direction = digitalio.Direction.INPUT
pin.pull = digitalio.Pull.UP
switch = Debouncer(pin)

while True:
    switch.update()
    if switch.fell:
        print("pressed")
```

`Debouncer` reads the pin only when `update()` runs.  In a busy loop, a quick tap can start and end between two reads and never show up.

The same button with `chumicro_buttons`:

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)   # wired between GP14 and GND

while True:
    now = ticks_ms()
    button.check(now)
    if button.just_pressed:
        led.value = not led.value
    if button.just_long_pressed:
        print("held for", button.held_ms, "ms")
```

Wire the button between the pin and GND.  `Button` switches on the pin's pull-up.  `ticks=ticks` hands `Button` the `chumicro_timing` clock it measures presses with.

`button.check(now)` collects every press since the last pass, including a tap the loop was too busy to see.  [Why does my button miss presses?](faq.md#why-does-my-button-miss-presses-while-the-board-is-doing-other-work) explains how.  `just_pressed` is `True` for exactly one pass per press.  Holding the button past half a second sets `just_long_pressed` once.

## Waiting for something: `Deadline`

Arduino code saves `pressedAt = millis()` and later checks `millis() - pressedAt >= 5000`.  A `Deadline` holds one such wait.  In this program, the LED comes on with each press and goes off five seconds after the last one:

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import Deadline, ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)
light_timer = Deadline(5000, ticks_ms())

while True:
    now = ticks_ms()
    button.check(now)
    if button.just_pressed:
        led.value = True
        light_timer.reset(now)   # five seconds from this press
    if led.value and light_timer.expired(now):
        led.value = False
```

## Two things at once: `Runner`

Every loop so far reads the clock, asks each thing whether it is due, and does the work.  `chumicro_runner` does the asking once the loop holds more than a couple of things:

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_runner import Runner
from chumicro_timing import ticks

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def blink(now_ms):
    led.value = not led.value


def pressed():
    print("pressed")


button = Button(pin=board.GP14, ticks=ticks)
button.on_press = pressed

runner = Runner()
runner.add_periodic(blink, period_ms=500)   # every 500 ms
runner.add(button, period_ms=20)            # look at the button every 20 ms

while True:
    now_ms = runner.tick()   # run everything that is due now
    runner.wait(now_ms)      # sleep until the next thing is due
```

The loop is still on the page as `while True:`.  `runner.tick()` runs whatever is due and returns the time it used.  `runner.wait(now_ms)` sleeps until the next thing is due.  The board idles between blinks and button checks instead of spinning through empty passes.

`WifiService`, `MQTTClient`, and `Button` all join a runner with `runner.add(...)`.  A program grows by lines above the loop.  The loop itself stays these two lines.

## WiFi that comes back: `WifiService`

A Learn guide joins WiFi like this:

```python
import os

import wifi

wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
print("connected:", wifi.radio.ipv4_address)
```

The program stops at `connect()` until the board joins or `connect()` raises an error.  When the router drops later, the next network call raises an exception.  Your code then has to reconnect.

`chumicro_wifi` runs the connection as a service on the runner.  The service joins, retries, and rejoins after a drop on its own:

```python
import board
import digitalio
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def blink(now_ms):
    led.value = not led.value


def show_wifi(old_state, new_state):
    print("wifi:", old_state, "->", new_state)


config = load_runtime_config()   # your wifi name and password, from the next section
wifi = WifiService.from_config(config)
wifi.on_state_change(show_wifi)

runner = Runner()
runner.add(wifi)
runner.add_periodic(blink, period_ms=500)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Unplug your router while this runs.  The console prints `wifi: connected -> reconnecting`.  Once the router is back, it prints `wifi: reconnecting -> connected`.  On MicroPython, the LED blinks the whole time.  On CircuitPython, the LED pauses during each join attempt and blinks between them.  [Does anything ever block?](faq.md#does-anything-ever-block) explains the pause.

## Your password: `secrets.toml`

Learn guides put the password in `settings.toml` or `secrets.py` on the CIRCUITPY drive.  Arduino sketches put it in `arduino_secrets.h`.  ChuMicro keeps it in `secrets.toml` at the top of your workspace, on your laptop, where git ignores it:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

Each deploy copies those values onto the board.  `WifiService.from_config(config)` picks out `wifi.ssid` and `wifi.password`.  [Wiring WiFi credentials](wiring-wifi-credentials.md) shows how the values reach the board, why `CIRCUITPY_WIFI_SSID` stays out of `settings.toml`, and how to run without a workspace.

## Uploading: dragging to CIRCUITPY becomes `deploy`

Dragging `code.py` and a `lib/` folder onto CIRCUITPY still works.  [Installing libraries](install.md) puts the libraries on with circup or mip.  Every program on this page except the WiFi one runs as a plain `code.py` or `main.py`.

A workspace from [Start here](start-here.md) adds `run.py deploy`, which does the job of Arduino's Upload button and Serial Monitor:

```bash
python3 run.py deploy blinker             # copy the project to the board and run it
python3 run.py deploy blinker --tail 30   # the same, then show 30 seconds of output
python3 run.py repl                       # open the board's REPL
```

Your code stays on your laptop under version control.  Each deploy copies it to the board with the libraries it imports and the settings from `secrets.toml`.  A deploy makes the board's files match the project, so a file copied there by hand disappears on the next deploy.  [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md) shows where each kind of file belongs.

## Cheat sheet

| Arduino or Adafruit Learn | ChuMicro |
|---|---|
| `setup()` | The code above `while True:` |
| `loop()` | The body of `while True:` |
| `delay(500)`, `time.sleep(0.5)` | `blink = Rate(500, ticks_ms())`, then `if blink.due(now):` |
| `millis()`, `time.monotonic()` | `ticks_ms()`, compared with `ticks_diff(now, then)` |
| `millis() - pressedAt >= 5000` | `timer = Deadline(5000, now)`, then `if timer.expired(now):` |
| `Debouncer(pin)`, `switch.fell` | `Button(pin=..., ticks=ticks)`, `button.just_pressed` |
| Several jobs in one `loop()` | A `Runner`, with `runner.tick()` and `runner.wait(now_ms)` in `while True:` |
| `wifi.radio.connect(...)` | `WifiService.from_config(config)`, added to the runner |
| `settings.toml`, `secrets.py`, `arduino_secrets.h` | `secrets.toml` in your workspace |
| Upload button, dragging to CIRCUITPY | `python3 run.py deploy <project>` |
| Serial Monitor | `python3 run.py repl`, or `deploy --tail` |

## On MicroPython

Build the LED and the button from `machine.Pin`:

```python
from chumicro_buttons import Button
from chumicro_timing import ticks
from machine import Pin

led = Pin("LED", Pin.OUT)                   # Pin(2, Pin.OUT) on many ESP32 boards
button = Button(pin=Pin(14), ticks=ticks)   # wired between GPIO 14 and GND
```

Read the LED with `led.value()`, set it with `led.value(1)`, and flip it with `led.value(not led.value())`.  Code that uses `chumicro_timing`, `chumicro_buttons`, `chumicro_runner`, and `chumicro_wifi` reads the same on both runtimes.

## Where to go next

- [Start here](start-here.md) sets up a workspace and gets your own project onto a board.
- [Build a WiFi temperature sensor](tutorial-wifi-sensor.md) grows the blink on this page, one step at a time, into a board that publishes its temperature over MQTT.
- [How it works](how-it-works.md) builds from a plain `while True:` loop up to a runner and a deploy.
- [Glossary](glossary.md) defines the ChuMicro words on this page.
- [Questions people ask](faq.md) covers why a board freezes on the network, what the libraries cost in flash, and testing without hardware.
- [The runner guide](https://chumicro.com/ChuMicro/runner/stable/) goes further into `tick()` and `wait()`.
- [The demos](https://github.com/ChuMicro/ChuMicro/tree/main/demos) are complete programs, each ending in the same `while True:` loop.
