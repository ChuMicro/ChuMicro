# chumicro-buttons

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Buttons that catch the press even when your loop is busy.**

`chumicro-buttons` reads a button wired to a pin and reports each press through `button.just_pressed`, in the `while True:` loop you already have.  A press lands whether the program was idle or halfway through a slow network call.  Debouncing, long presses, auto-repeat, and double-click counting come with it.  The same code runs on CircuitPython, MicroPython, and CPython.

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

The `Runner` loop in the quick example comes from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Toggle the onboard LED with a button on a CircuitPython board.  On a Pi Pico W, wire a momentary button from GP14 to GND.  On an ESP32-S2 board, use IO14 and `board.IO14`.  The library switches on the pin's internal pull-up, so the button is the only part:

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = Button(pin=board.GP14, ticks=ticks)    # ticks: the clock it times presses with

while True:
    now_ms = ticks_ms()
    button.check(now_ms)                # collect what the button did, without waiting

    if button.just_pressed:             # True on exactly one pass per press
        led.value = not led.value
```

The loop never pauses, so code you add to it keeps running between presses.  `just_pressed` is `True` on exactly one pass per press.  Reading it twice in that pass gives the same answer.  Nothing needs to clear it.

On MicroPython, pass a `machine.Pin`: `Button(pin=Pin(14), ticks=ticks)`.

In `adafruit_debouncer` terms, `check()` is `update()` and `just_pressed` is `Button.pressed`.  Here `pressed` is the held-down level, `True` for as long as the button is down.  Arduino's Debounce sketch keeps `lastDebounceTime` by hand.  Here `check()` does that bookkeeping.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) and let a callback react to the press:

```python
from chumicro_runner import Runner

button.on_press = lambda: print("pressed")

runner = Runner()
runner.add(button, period_ms=20)        # look at the button every 20 ms

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`runner.tick()` checks the button and calls `on_press` on the pass a press lands.  `runner.wait(now_ms)` sleeps until the next job is due.  A press cannot wake the runner, so `period_ms=20` has it look at the button every 20 ms.  Without `period_ms`, a press waits for whatever wakes the runner next, which can be seconds in a program with a slow job.

## Presses land even when the loop is slow

A tap is short.  When the loop is busy with a network request or a flash write, a plain pin read comes too late and misses the press.  `chumicro-buttons` records the press when it happens and reports it on the next pass.

On CircuitPython the firmware's own `keypad` module records presses in the background and stamps each one with the time it happened.  On MicroPython the library installs a small pin interrupt that does the same job.  Either way, durations measure the press the person actually made:

```python
button.check(now_ms)
if button.just_pressed:
    print(button.held_ms)      # counted from the real press, not from this pass
```

The library picks the recording method for the runtime, so the code stays the same on both.

## Debouncing

A button is two pieces of metal meeting.  They bounce apart a few times before they settle, so one press can read as several.  *Debouncing* ignores that chatter.  `chumicro-buttons` debounces every button.

`settle_ms` is the only setting.  A change counts once the pin has held its new level that long.  It defaults to 10, which suits an ordinary tactile button:

```python
button = Button(pin=board.GP14, ticks=ticks, settle_ms=10)   # the default
button = Button(pin=board.GP14, ticks=ticks, settle_ms=0)    # the signal is already clean
```

Set it to `0` when debouncing hardware sits behind the button.  That drops the 10 ms wait before a press is reported.  The [guide](https://chumicro.com/ChuMicro/buttons/stable/guide/) shows that wiring with component values, and when it is worth the parts.

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
| `button.overflowed` | `True` when a signal was too noisy to record in full |

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
| `chumicro_buttons.testing.FakeButtonSource` | A stand-in for the pin that a test presses and releases by hand, so button logic runs with no board |

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing), which installs with it.  Your program hands the `ticks` module to each button as `ticks=`.  The library imports no clock itself, so a program can pass a different clock there.

Runs as a service on a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) loop, as the quick example shows.  A rotary encoder's push switch is a `Button` like any other, so an encoder with a click uses this library alongside [`chumicro-knobs`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs).

## Platform support

Works on CPython, MicroPython, and CircuitPython.  CircuitPython's `keypad` module is built into the firmware, so it takes no space on the board's drive.  On a laptop, `pin=` raises an error that points to `FakeButtonSource`.

## Testing your code

`FakeButtonSource` from `chumicro_buttons.testing` stands in for the hardware, so press logic becomes an ordinary unit test with no board and no waiting:

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

Each queued press or release carries its own `at_ms`, separate from the time passed to `check()`.  That gap lets a test act out a slow loop on a laptop.

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
