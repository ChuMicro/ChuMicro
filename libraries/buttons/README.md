# chumicro-buttons

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Buttons that catch the press even when your loop is busy.**

Wire a button to a pin, read `button.just_pressed` in the loop you already wrote, and the press lands whether your program was idle or halfway through a slow network call.  Debouncing, long presses, auto-repeat, and double-click counting come with it, and the same code runs on CircuitPython, MicroPython, and your laptop.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_buttons

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_buttons

# CPython
pip install chumicro-buttons
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

Toggle the onboard LED with a button on a CircuitPython board.  Wire a momentary button from GP14 to GND on a Pi Pico W (on an ESP32-S2 board, IO14 and `board.IO14`).  The pin's internal pull-up is switched on for you, so the button is the only part.

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)    # ticks: the clock it times presses with

while True:
    now = ticks_ms()
    button.check(now)                   # collect what the button did; never waits

    if button.just_pressed:             # True on exactly one pass per press
        led.value = not led.value
```

The loop never pauses, so code you add to it keeps running between presses.  `just_pressed` is true on one pass per press, so you can read it as often as you like in that pass without it firing twice, and you never clear it.

On MicroPython, pass a `machine.Pin`: `Button(pin=Pin(14), ticks=ticks)`.

Coming from `adafruit_debouncer`: `check()` is `update()`, `just_pressed` is its `Button.pressed`, and `pressed` here is the held-down level, true for as long as the button is down.  Coming from Arduino: the Debounce sketch's `lastDebounceTime` bookkeeping happens inside `check()`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) and let a callback react to the press:

```python
from chumicro_runner import Runner

button.on_press = lambda: print("pressed")

runner = Runner()
runner.add(button, period_ms=20)        # look at the button every 20 ms

while True:
    now = runner.tick()
    runner.wait(now)
```

`runner.tick()` checks the button and calls `on_press` on the pass a press lands.  `runner.wait(now)` rests the CPU until the next job is due.  A press cannot wake the runner, so `period_ms=20` has it look at the button every 20 ms; without it, a press waits for whatever wakes the runner next, which in a program with a slow job can be seconds.

## Presses land even when the loop is slow

A tap is short.  If your loop is busy with a network request or a flash write when it happens, a plain pin read looks too late and the press is gone.  This library captures the press when it happens, not when your loop gets round to asking.

On CircuitPython the firmware's own `keypad` module does the capturing in the background and stamps each press with the time it happened.  On MicroPython the library installs a small pin interrupt that does the same job.  Either way, durations measure the press the person actually made:

```python
button.check(now)
if button.just_pressed:
    print(button.held_ms)      # counted from the real press, not from this pass
```

You set none of this up.  There is no capture mode to pick and no interrupt to write.

## What's included

### Core

| Symbol | Description |
|---|---|
| `Button(pin, settle_ms=10, ...)` | One momentary button or switch on one pin |
| `Buttons(pins, ...)` | Several keys on one scan, read as `buttons[0]`, `buttons[1]` |
| `KeyMatrix(row_pins, column_pins, ...)` | A keypad wired as rows by columns, numbered row-major.  Imported from `chumicro_buttons.matrix` |

### Readings, refreshed by `check(now_ms)`

| Symbol | Description |
|---|---|
| `button.pressed` | `True` while the key is down, after debouncing |
| `button.just_pressed` | `True` only on the pass the press landed |
| `button.just_released` | `True` only on the pass the release landed |
| `button.just_long_pressed` | `True` only on the pass a press reached `long_press_ms` |
| `button.just_repeated` | `True` on each pass auto-repeat fires while the key is held.  Set `repeat_ms` to turn it on |
| `button.just_clicked` | `True` only on the pass a run of quick presses ended.  Set `click_ms` to turn it on |
| `button.held_ms` | Milliseconds the key has been down, counted from the real press.  After a release it holds how long that press lasted |
| `button.click_count` | How many quick presses were in the run that just ended: 2 for a double click |
| `button.overflowed` | `True` when a signal was too noisy to capture in full |

### Callbacks, dispatched by `handle(now_ms)`

| Symbol | Description |
|---|---|
| `button.on_press` | Called with no arguments when the key goes down |
| `button.on_release` | Called with no arguments when the key comes up |
| `button.on_long_press` | Called once per press, after `long_press_ms` |
| `button.on_repeat` | Called on each auto-repeat while the key is held |
| `button.on_click` | Called with `click_count` when a run of quick presses ends |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_buttons.testing.FakeButtonSource` | Hand-driven edge source, so button logic is testable with no board |

## Debouncing

A button is two pieces of metal meeting, and they bounce apart a few times before they settle.  Left alone, one press reads as several.  *Debouncing* is ignoring that chatter, and this library does it for every button.

`settle_ms` is the only setting.  A change counts once the pin has held its new level that long.  It defaults to 10, which suits an ordinary tactile button:

```python
button = Button(pin=board.GP14, ticks=ticks, settle_ms=10)   # the default
button = Button(pin=board.GP14, ticks=ticks, settle_ms=0)    # the signal is already clean
```

For most projects the default is enough.  Set it to `0` when the button has debouncing hardware behind it, which drops the 10 ms wait before a press is reported.  The [guide](https://chumicro.com/ChuMicro/buttons/stable/guide/) shows that wiring with component values, and when it is worth the parts.

## Where this fits

Installing `chumicro-buttons` brings [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) with it, and your program hands its `ticks` module to each button as `ticks=`.  The library imports nothing on its own, so a program that keeps time some other way can pass its own clock there instead.

Pairs with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), which runs every service in your program from one loop:

```python
runner.add(button, period_ms=20)    # the runner calls check() and handle() every 20 ms
```

A rotary encoder's push switch is a `Button` like any other, so an encoder with a click uses this library alongside [`chumicro-knobs`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

CircuitPython reads keys with the firmware's own `keypad` module, which scans in the background and takes no space on your board's drive because it is built into the firmware.  MicroPython has no equivalent, so the library installs and owns a pin interrupt there.  Either way the code you write is the same, and you set none of it up.

`pin=` needs real hardware, so on a laptop it raises and points you at the fake below.

## Testing your code

The `chumicro_buttons.testing` module provides `FakeButtonSource`, a hand-driven stand-in for the hardware, so press logic is an ordinary unit test with no board and no waiting:

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks

source = FakeButtonSource()
button = Button(source=source, ticks=FakeTicks())

source.press(at_ms=100)
button.check(120)

assert button.just_pressed
assert button.held_ms == 20      # counted from the press, not from the check
```

Each queued press or release carries its own `at_ms`, separate from the time you pass to `check()`.  That gap is what lets a test cover a slow loop on your laptop.

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/circuitpython_button_toggle.py) | The quick example as a full program: a press flips the onboard LED, and a half-second hold turns it off |
| [`micropython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/micropython_button_toggle.py) | The same program on MicroPython |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/buttons/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/buttons/experimental/)**

## Find this library

- **PyPI:** [chumicro-buttons](https://pypi.org/project/chumicro-buttons/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_buttons) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_buttons)
- **Source:** [libraries/buttons](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
