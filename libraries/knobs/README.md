# chumicro-knobs

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Rotary encoders and analog knobs, read as a number that holds still.**

Turn a shaft and `encoder.position` counts the clicks.  Turn a potentiometer and `knob.value` lands on a step and stays there.  A fast spin arrives whole even when your loop was busy elsewhere, a parked wiper keeps reporting the same number, and the same code runs on CircuitPython, MicroPython, and your laptop.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_knobs

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_knobs

# CPython
pip install chumicro-knobs
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

Wire the encoder's two signal pins to GPIO pins and its common pin to GND.  The internal pull-ups are switched on for you, so no extra parts are needed.

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))

while True:
    now = ticks_ms()
    volume.check(now)

    if volume.just_moved:                    # true only on the tick the shaft moved
        print("volume", volume.position)     # walks 0 to 20 and stops at both ends
```

The loop never pauses, so the rest of your program keeps running between turns.  `just_moved` is true for exactly one pass, which means you can read it as many times as you like without it firing twice.

## A fast spin arrives whole

An encoder reports movement as pulses on two signal pins, and one brisk flick of the wrist sends dozens of them.  If your loop stalls on a socket read or a flash write, a plain pin read looks at the wrong moments and most of the turn is gone.  The counting here happens outside your loop, so a tick that arrives late still reads the whole spin.

On CircuitPython that counting is `rotaryio`, running in the firmware's own C, which on RP2040 boards is a state machine in the PIO block.  On MicroPython the library installs an interrupt on both signal pins and decodes the pulses itself.  Your program sets up neither one; it reads `position` on whichever runtime it happens to be on.

```python
volume.check(now)
if volume.just_moved:
    print(volume.delta)      # every detent of the spin, even the ones during the stall
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Encoder(pin_a, pin_b, detent_steps=4, bounds=None, wrap=False)` | One rotary encoder on two signal pins, counted in detents |
| `AnalogKnob(pin, steps=100, deadband=512)` | One potentiometer or slider on one analog pin, read as a step number |
| `knob.check(now_ms)` | Take one reading; returns `True` when the number changed |
| `knob.handle(now_ms)` | Call `on_change` when the tick earned it |
| `knob.deinit()` | Hand the pins back, along with any interrupt the library installed |

### Readings, refreshed by `check(now_ms)`

| Symbol | Description |
|---|---|
| `encoder.position` | Detents counted so far, held inside `bounds` when there are any.  Assign to it to restore a saved value |
| `encoder.delta` | Detents this tick added to `position`, negative the other way round |
| `encoder.just_moved` | `True` only on the tick `position` changed |
| `knob.value` | Where the knob points, `0` at one end of the sweep and `steps - 1` at the other |
| `knob.delta` | Steps this tick added to `value`, negative the other way round |
| `knob.raw` | The settled 0 to 65535 reading `value` was worked out from |
| `knob.just_moved` | `True` only on the tick `value` changed |

### Callbacks, dispatched by `handle(now_ms)`

| Symbol | Description |
|---|---|
| `encoder.on_change` | Called with the signed detent change when the shaft turns |
| `knob.on_change` | Called with the new step number when the knob moves |

### Defaults you can import

| Symbol | Description |
|---|---|
| `DEFAULT_DETENT_STEPS` | `4`, the pulses one click of a detented encoder produces |
| `DEFAULT_STEPS` | `100` positions across a full sweep of an analog knob |
| `DEFAULT_DEADBAND` | `512`, how far a reading moves before `value` follows it |
| `RAW_RANGE` | `65536`, the raw scale every runtime reports a conversion on |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_knobs.testing.FakeEncoderSource` | A shaft your test turns by hand, so encoder logic runs with no board |
| `chumicro_knobs.testing.FakeAnalogSource` | A wiper your test parks where it likes, so the deadband is testable too |

## The reading holds still

A potentiometer's voltage is never exactly steady.  The low bits of a 12-bit converter wander a couple of counts under a parked wiper, which is 32 counts once the reading is scaled to the 0 to 65535 range every runtime reports on, and a noisier part on a long lead wanders several times that.  A program that prints the raw reading shows a knob somebody is fiddling with.

`deadband` is how far the reading has to move before `value` follows it, and quantizing into `steps` gives the number a size a person can aim at:

```python
brightness = AnalogKnob(board.A0, steps=10)                # reports 0 to 9
fine = AnalogKnob(board.A1, steps=256, deadband=128)       # a finer sweep, a tighter deadband
```

The default 512 sits well above the wander and well under the 655 counts one step spans at 100 steps.  Keep `deadband` under the width of one step, which is `65536 // steps` counts, so every step stays reachable including the ones at the ends of the sweep.

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing), whose `ticks_ms()` is where the timestamp you hand to `check()` comes from.  Used directly in user apps; nothing downstream depends on it.

Pairs with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), which deals out turns to every service in your program:

```python
runner.add(volume)      # check() and handle() are the runner's contract
```

A rotary encoder's push switch is a button on its own pin, so an encoder with a click reads its shaft here and its switch with [`chumicro-buttons`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

### RP2040 wants adjacent pins

`rotaryio` on RP2040 boards reads the two signal pins with one PIO state machine, which requires them to sit next to each other in GPIO numbering.  `board.GP16` and `board.GP17` work; `board.GP16` and `board.GP20` do not.  Other CircuitPython ports and every MicroPython port take any two pins.

### CPython has no pins

`Encoder(pin_a, pin_b)` and `AnalogKnob(pin)` need real hardware, so on a laptop they raise and tell you what to do instead.  Build the knob with a fake source and your logic becomes an ordinary unit test:

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
| [`knob_readings_simulated.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/knob_readings_simulated.py) | An encoder hitting its bounds and a deadband holding an analog reading still, on CPython, no board needed |
| [`circuitpython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/circuitpython_encoder_volume.py) | An encoder for volume and a potentiometer for brightness on CircuitPython |
| [`micropython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/micropython_encoder_volume.py) | The same two knobs on MicroPython |

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
