# chumicro-knobs

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Rotary encoders and analog knobs, read as a number that holds still.**

Turn a rotary encoder and `encoder.position` counts the clicks.  Turn a potentiometer and `knob.value` lands on a step and stays there.  A fast spin is counted in full even when your loop was busy elsewhere, a knob you have let go of keeps reporting the same number, and the same code runs on CircuitPython, MicroPython, and your laptop.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_knobs chumicro_timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_knobs
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython
pip install chumicro-knobs chumicro-timing
```

`chumicro-knobs` needs no other library.  The examples read the clock with `chumicro-timing`, so install it alongside.

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

Turn a rotary encoder to change a number on a CircuitPython board.  On a Pi Pico W, wire the encoder's two signal pins (often labelled CLK and DT) to GP16 and GP17 and its common pin to GND; on an ESP32-S2 board, use IO16 and IO17.  The pins' internal pull-ups are switched on for you.

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))    # holds the number between 0 and 20

while True:
    now = ticks_ms()
    volume.check(now)                       # read how far the shaft turned; never waits

    if volume.just_moved:                   # True on exactly one pass per change
        print("volume", volume.position)
```

Each click you feel as the shaft turns is a *detent*, and `position` moves by one per detent.  If yours moves only on every other click, pass `detent_steps=2`.  If you have used `rotaryio.IncrementalEncoder`, `position` here is its `position`, and `check()` does the `if position != last_position` bookkeeping for you.

On MicroPython, pass `machine.Pin` objects: `Encoder(Pin(16), Pin(17), bounds=(0, 20))`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) and let a callback react to the turn:

```python
from chumicro_runner import Runner

volume.on_change = lambda detents: print("volume", volume.position)

runner = Runner()
runner.add(volume, period_ms=20)        # read the encoder fifty times a second

while True:
    now = runner.tick()
    runner.wait(now)
```

`runner.tick()` checks the encoder and calls `on_change` on the pass it turned.  `runner.wait(now)` rests the CPU until the next job is due, and turning a knob cannot wake it, so `period_ms=20` has the runner read the encoder fifty times a second, faster than a hand turns.

## A fast spin is counted in full

An encoder reports turning as pulses on its two signal pins, and one quick flick of the wrist sends dozens of them.  If your loop is busy with a network request or a flash write while they arrive, a plain pin read misses most of the turn.  Here the counting happens outside your loop, so a pass that comes round late still sees the whole spin.

On CircuitPython the firmware's `rotaryio` module does the counting.  On MicroPython the library puts an interrupt on both signal pins and counts the pulses itself.  You set up neither one:

```python
volume.check(now)
if volume.just_moved:
    print(volume.delta)      # every detent of the spin, including any your loop was too busy to see
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Encoder(pin_a, pin_b, detent_steps=4, bounds=None, wrap=False)` | One rotary encoder on two signal pins, counted in detents |
| `AnalogKnob(pin, steps=100, deadband=512)` | One potentiometer or slider on one analog pin, read as a step number |
| `knob.check(now_ms)` | Take one reading; returns `True` when the number changed |
| `knob.handle(now_ms)` | Call `on_change` when this pass's `check()` found a change |
| `knob.deinit()` | Hand the pins back, along with any interrupt the library installed |

### Readings, refreshed by `check(now_ms)`

| Symbol | Description |
|---|---|
| `encoder.position` | Detents counted so far, held inside `bounds` when there are any.  Assign to it to restore a saved value |
| `encoder.delta` | Detents this pass added to `position`, negative the other way round |
| `encoder.just_moved` | `True` only on the pass `position` changed |
| `knob.value` | Where the knob points, `0` at one end of the sweep and `steps - 1` at the other |
| `knob.delta` | Steps this pass added to `value`, negative the other way round |
| `knob.raw` | The smoothed 0 to 65535 reading `value` was worked out from |
| `knob.just_moved` | `True` only on the pass `value` changed |

### Callbacks, dispatched by `handle(now_ms)`

| Symbol | Description |
|---|---|
| `encoder.on_change` | Called with the signed detent change when the shaft turns |
| `knob.on_change` | Called with the new step number when the knob moves |

### Defaults you can import

| Symbol | Description |
|---|---|
| `DEFAULT_DETENT_STEPS` | `4`, the steps one click of a typical encoder produces |
| `DEFAULT_STEPS` | `100` positions across a full sweep of an analog knob |
| `DEFAULT_DEADBAND` | `512`, how far a reading moves before `value` follows it |
| `RAW_RANGE` | `65536`, the raw scale every runtime reports a conversion on |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_knobs.testing.FakeEncoderSource` | A shaft your test turns by hand, so encoder logic runs with no board |
| `chumicro_knobs.testing.FakeAnalogSource` | A wiper your test parks where it likes, so the deadband is testable too |

## A potentiometer that holds still

Wire the potentiometer's outer legs to 3V3 and GND and its middle leg to an analog pin, such as `board.A0` (GP26 on a Pi Pico W).  `steps` divides its travel into numbered positions, and `value` reports which one the knob points at:

```python
from chumicro_knobs import AnalogKnob

brightness = AnalogKnob(board.A0, steps=10)     # reports 0 to 9

while True:
    now = ticks_ms()
    brightness.check(now)

    if brightness.just_moved:
        print("brightness", brightness.value)
```

An analog reading is never exactly steady, and printed as it comes it looks like a knob somebody is fiddling with.  `AnalogKnob` throws away lone bad samples, smooths the rest, and moves `value` only when the reading has moved by more than `deadband`, so a knob you have let go of keeps its number.  `knob.raw` is that smoothed reading, on the same 0 to 65535 scale as `analogio.AnalogIn.value`.

The default `deadband` of 512 suits the default 100 steps.  Keep it below the width of one step, `65536 // steps`, so every step stays reachable, which means a finer sweep wants a tighter deadband:

```python
fine = AnalogKnob(board.A1, steps=256, deadband=128)
```

## Where this fits

Needs no other library.  The time you hand to `check()` comes from wherever your loop already gets one, usually `ticks_ms()` from [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).  Used directly in your programs; no other ChuMicro library depends on it.

Pairs with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), which runs every service in your program from one loop:

```python
runner.add(volume, period_ms=20)    # the runner calls check() and handle() every 20 ms
```

A rotary encoder's push switch is a button on its own pin, so an encoder with a click reads its shaft here and its switch with [`chumicro-buttons`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

### A Pico wants its encoder pins side by side

On RP2040 boards such as the Pi Pico W, CircuitPython's `rotaryio` counts with the chip's PIO hardware, which needs the two signal pins next to each other in GPIO numbering.  `board.GP16` and `board.GP17` work; `board.GP16` and `board.GP20` do not.  Other CircuitPython boards and every MicroPython board take any two pins.

`pin_a`, `pin_b`, and `pin` need real hardware, so on a laptop they raise and point you at the fakes below.

## Testing your code

The `chumicro_knobs.testing` module provides `FakeEncoderSource` and `FakeAnalogSource`, hand-driven stand-ins for the hardware, so knob logic is an ordinary unit test with no board:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource

source = FakeEncoderSource()
volume = Encoder(source=source, bounds=(0, 20))

source.turn(3)
volume.check(0)

assert volume.position == 3
```

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/circuitpython_encoder_volume.py) | The quick example as a full program: an encoder sets a volume from 0 to 20 and a potentiometer sets a brightness from 0 to 9, on CircuitPython |
| [`micropython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/micropython_encoder_volume.py) | The same program on MicroPython |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/knobs/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/knobs/experimental/)**

## Find this library

- **PyPI:** [chumicro-knobs](https://pypi.org/project/chumicro-knobs/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_knobs) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_knobs)
- **Source:** [libraries/knobs](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
