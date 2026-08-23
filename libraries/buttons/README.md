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

Wire a momentary button between a GPIO pin and GND.  The internal pull-up is switched on for you, so no extra parts are needed.

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

button = Button(pin=board.GP14, ticks=ticks)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

while True:
    now = ticks_ms()
    button.check(now)

    if button.just_pressed:              # true only on the tick the press landed
        led.value = not led.value
```

The loop never pauses, so the rest of your program keeps running between presses.  `just_pressed` is true for exactly one pass, which means you can read it as many times as you like without it firing twice.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) and let callbacks do the reading:

```python
from chumicro_runner import Runner

button.on_press = lambda: print("pressed")

runner = Runner()
runner.add(button)

while True:
    now = runner.tick()
    runner.wait(now)
```

`tick()` gives every registered service one small step and dispatches your callbacks; `wait()` parks the CPU until the next event, waking exactly when a long press, a repeat, or a click window is due.

## Presses land even when the loop is slow

A tap is short.  If your loop stalls on a socket read or a flash write, a naive pin read looks at the wrong moment and the press is gone.  This library captures the edge when it happens instead of when you get around to asking.

On CircuitPython that capture is the firmware's own `keypad` scan, which runs in the background and stamps each edge with the time it happened.  On MicroPython the library installs a small interrupt handler and does the same job.  Either way the timing you read is the press the person actually performed:

```python
button.check(now)
if button.just_pressed:
    print(button.held_ms)      # measured from the real edge, not from this tick
```

You never set any of this up.  There is no capture mode to pick and no interrupt to write.

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
| `button.just_pressed` | `True` only on the tick the press landed |
| `button.just_released` | `True` only on the tick the release landed |
| `button.held_ms` | Milliseconds the key has been down, measured from the real edge.  After a release it holds how long that press lasted |
| `button.click_count` | Presses in the click series that just closed |
| `button.overflowed` | `True` when a signal was too noisy to capture in full |

### Callbacks, dispatched by `handle(now_ms)`

| Symbol | Description |
|---|---|
| `button.on_press` | Called with no arguments when the key goes down |
| `button.on_release` | Called with no arguments when the key comes up |
| `button.on_long_press` | Called once per press, after `long_press_ms` |
| `button.on_repeat` | Called on each auto-repeat while the key is held |
| `button.on_click` | Called with the press count when a click series closes |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_buttons.testing.FakeButtonSource` | Hand-driven edge source, so button logic is testable with no board |

## Debouncing

A switch is two pieces of metal meeting, and they bounce apart a few times on the way.  Left alone, one press reads as several.

`settle_ms` is the only setting.  It defaults to 10, which suits an ordinary tactile switch:

```python
button = Button(pin=board.GP14, ticks=ticks, settle_ms=10)   # the default
button = Button(pin=board.GP14, ticks=ticks, settle_ms=0)    # the signal is already clean
```

Set it to `0` when the button has debouncing hardware behind it, which buys back the settle delay.  The [guide](https://chumicro.com/ChuMicro/buttons/stable/guide/) has wiring diagrams with real component values for building that, and an honest account of when it is worth the parts.  For most projects the default is enough.

## Where this fits

Imports nothing.  It compares durations using the tick arithmetic you hand it, which is what `ticks=` is for, and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) supplies the usual one.  Bring your own and this library never loads it.  Used directly in user apps; nothing downstream depends on it.

Pairs with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), which deals out turns to every service in your program:

```python
runner.add(button)      # check() and handle() are the runner's contract
```

A rotary encoder's push switch is a `Button` like any other, so an encoder with a click uses this library alongside [`chumicro-knobs`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

CircuitPython reads keys through the firmware's own background scan, which costs nothing in your board's storage because it is compiled into the firmware.  MicroPython has no equivalent, so the library installs and owns a capture interrupt there.  Either way the API is the same and you set none of it up.

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
assert button.held_ms == 20      # measured from the edge, not from the tick
```

Each queued edge carries its own `at_ms`, separate from the tick you pass to `check()`.  That gap is what lets a test cover slow-loop behavior on the host.

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/circuitpython_button_toggle.py) | A button flips the onboard LED on CircuitPython |
| [`micropython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/micropython_button_toggle.py) | The same button on MicroPython |

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
