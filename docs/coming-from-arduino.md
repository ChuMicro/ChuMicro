---
title: "Coming from Arduino: setup(), loop(), millis(), and while True with ChuMicro"
---

# Coming from Arduino

This page is for you if you learned boards from Arduino's `setup()` and `loop()`, or from an Adafruit Learn guide whose `code.py` ends in `while True:` with a `time.sleep()` inside.  Each section takes one habit you already have and shows the ChuMicro version next to it, your familiar code first.

The examples use CircuitPython's `board` and `digitalio`.  On MicroPython only the pin lines change, and [On MicroPython](#on-micropython) near the end shows them.

## What stays the same

It is still Python running on the board, CircuitPython or MicroPython, from a `code.py` or a `main.py`.  You still set up pins with your runtime's own `board` and `digitalio` or `machine.Pin`, you still `print()` to the serial console, and your program still ends in a `while True:` loop that runs until the power goes.

If you come from Arduino, the code above `while True:` is your `setup()`, and the body of the loop is your `loop()`.

## What changes: your code checks the clock instead of sleeping

`time.sleep(1)` and `delay(1000)` stop the whole board for a second.  With one LED nobody notices.  Add a button, a sensor, and a wifi connection, and every sleep is a second where the button goes unread and the network goes unanswered.

ChuMicro code checks the clock instead.  Each pass through the loop asks whether anything is due, does the work that is, and moves on.  Every section below applies that idea to a habit you already have.  The program still sleeps in one spot, `runner.wait()`, and only until the next job is due; [Two things at once](#two-things-at-once-runner) shows it.

## Blink: `time.sleep()` becomes `Rate`

The blink you know:

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

`ticks_ms()` reads the clock in milliseconds, like Arduino's `millis()`.  `blink.due(now)` answers `True` once every 500 ms and `False` on every other pass, so the loop is free in between.

If you know Arduino's BlinkWithoutDelay sketch, `Rate` is its `previousMillis` and `interval` folded into one object:

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

`Rate` also keeps to its schedule.  When a pass runs late, the next blink still lands on the 500 ms beat, where BlinkWithoutDelay starts counting again from the late moment and drifts.

`ticks_ms()` wraps back to zero about every 6.2 days, and Python integers do not wrap with it, so subtracting two tick values goes wrong across the wrap.  `ticks_diff(now, then)` gets it right, and `Rate` and `Deadline` use it for you.

## Buttons: debouncing becomes `chumicro_buttons`

The habit is to read the pin and sleep 20 ms to ride out contact bounce, or to reach for `adafruit_debouncer`:

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

`Debouncer` reads the pin when `update()` runs, so in a busy loop a quick tap can start and end between two reads and never show up.

With `chumicro_buttons`:

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

Wire the button between the pin and GND; `Button` switches on the pull-up.  `ticks=ticks` hands it the clock from `chumicro_timing` to measure presses with.

`button.check(now)` collects whatever happened since the last pass.  On CircuitPython the firmware's `keypad` module watches the pin in the background, and on MicroPython a pin interrupt does, so a quick tap still counts while the loop is busy.  `just_pressed` is `True` for exactly one pass per press, and holding past half a second sets `just_long_pressed` once.

## Waiting for something: `Deadline`

Arduino code saves `pressedAt = millis()` and later checks `millis() - pressedAt >= 5000`.  A `Deadline` holds one of those waits.  This LED comes on with each press and goes off five seconds after the last one:

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

Every loop so far has the same shape: read the clock, ask each thing whether it is due, do the work.  `chumicro_runner` does the asking for you once the loop has more than a couple of things in it:

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

The loop is still on the page, and it is still `while True:`.  `runner.tick()` runs whatever is due and returns the time it used.  `runner.wait(now_ms)` is where a ChuMicro program sleeps, and the runner works out how long: until the next thing is due, and no longer.  The board idles between blinks and button checks instead of spinning through empty passes.

The wifi service, the MQTT client, and buttons all join a runner with `runner.add(...)`, so a program grows by adding lines above the loop while the loop itself stays these two lines.

## WiFi that comes back: `WifiService`

The habit, from Learn guides:

```python
import os

import wifi

wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
print("connected:", wifi.radio.ipv4_address)
```

The program stops at `connect()` until the board joins or gives up with an error.  When the router drops later, the next network call raises, and reconnecting is your code's job.

`chumicro_wifi` runs the connection as a service on the runner.  It joins, retries after a failure with a pause that doubles from 1 second up to a minute, and rejoins after a drop on its own:

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


config = load_runtime_config()   # your wifi name and password; see the next section
wifi = WifiService.from_config(config)
wifi.on_state_change(show_wifi)

runner = Runner()
runner.add(wifi)
runner.add_periodic(blink, period_ms=500)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Unplug your router while this runs.  The console prints `wifi: connected -> reconnecting`, then `wifi: reconnecting -> connected` once the router is back.  On MicroPython the LED blinks the whole time.  On CircuitPython each join attempt holds the loop for up to 15 seconds, because the firmware only offers a connect call that waits, and the LED blinks again between attempts.

## Your password: `secrets.toml`

Learn guides put the password in `settings.toml` or `secrets.py` on the CIRCUITPY drive, and Arduino sketches put it in `arduino_secrets.h`.  ChuMicro keeps it in `secrets.toml` at the top of your workspace, on your laptop, where git ignores it:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

When you deploy, the tool converts that file and writes it to the board as `/runtime_config.msgpack`.  `load_runtime_config()` reads it back with each table name and key joined by a dot, so `ssid` under `[wifi]` becomes `config["wifi.ssid"]`.  `WifiService.from_config(config)` looks up `wifi.ssid` and `wifi.password` for you.

Keep `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD` out of `settings.toml`.  Those keys switch on CircuitPython's own auto-connect, which fights `WifiService` for the radio, and a workspace deploy removes `settings.toml` from the board for that reason.  [Wiring WiFi credentials](wiring-wifi-credentials.md) covers broker settings and running without a workspace.

## Uploading: dragging to CIRCUITPY becomes `deploy`

Dragging `code.py` and a `lib/` folder onto CIRCUITPY still works.  The libraries install with `circup` on CircuitPython or `mip` on MicroPython, and every program on this page except the wifi one runs as a plain `code.py` or `main.py`.

A workspace, set up in [Start here](start-here.md), adds a deploy command that does the job of Arduino's Upload button and Serial Monitor:

```bash
python3 run.py deploy blinker             # copy the project to the board and run it
python3 run.py deploy blinker --tail 30   # the same, then show 30 seconds of output
python3 run.py repl                       # open the board's REPL
```

Your code stays on your laptop under version control.  Each deploy copies it to the board along with the libraries you added to the workspace and the settings from `secrets.toml`.  A deploy replaces what is on the board, so files you copied there by hand go away; keep everything in the project.

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

Then read the LED with `led.value()` and set it with `led.value(1)`, or flip it with `led.value(not led.value())`.  Everything from `chumicro_timing`, `chumicro_buttons`, `chumicro_runner`, and `chumicro_wifi` reads the same on both runtimes.

## Where to go next

- [Start here](start-here.md) sets up a workspace and gets your own project onto a board.
- [Questions people ask](faq.md) covers why a board freezes on the network, what the libraries cost in flash, and testing without hardware.
- [The runner guide](https://chumicro.com/ChuMicro/runner/stable/) goes further into `tick()` and `wait()`.
- [The demos](https://github.com/ChuMicro/ChuMicro/tree/main/demos) are complete programs, each ending in the same `while True:` loop.
