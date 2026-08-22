# User Guide

## Overview

A knob tells your program where it has been turned to, and getting that from a pin takes more than one read.  A rotary encoder reports turning as pulses on two signal pins, arriving fast enough that a busy loop misses most of a flick of the wrist.  A potentiometer gives you a voltage that never sits exactly still, so a program that prints it raw reports a knob nobody is touching.

`chumicro_knobs` does that work.  `Encoder` reads a rotary encoder as a count of detents, the click you feel as the shaft turns, and `AnalogKnob` reads a potentiometer or slider as a step number out of however many steps you asked for.  Both are refreshed by `check(now_ms)`, both publish `delta` and `just_moved`, and both dispatch a callback from `handle(now_ms)`.

The main reading is named for what each device actually knows.  An encoder counts movement from wherever it started, so it publishes `position`; an analog knob points somewhere absolute along its sweep, so it publishes `value`.

## Getting started

Wire the encoder's two signal pins to GPIO pins and its common pin to GND.  The internal pull-ups are switched on for you, so no extra parts are needed.

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17)

while True:
    now = ticks_ms()
    volume.check(now)

    if volume.just_moved:
        print("volume", volume.position)
```

`check(now_ms)` does one small step: it collects the counting that happened since the last pass and folds it into `position`.  It never waits, so the rest of your program keeps running between turns.

On MicroPython the two pins are GPIO numbers or `machine.Pin` objects, and everything else on the page reads the same:

```python
from machine import Pin

volume = Encoder(Pin(16), Pin(17))
```

## Reading the encoder

Every reading is a plain attribute, refreshed by `check()`:

```python
volume.position       # detents counted so far
volume.delta          # detents this tick added to position
volume.just_moved     # True only on the tick position changed
```

`position` starts at zero and counts up as the shaft turns one way, down as it turns the other.  Swapping `pin_a` and `pin_b` swaps which way counts up, which is the fix when a knob reads backwards.

`delta` is the movement for this tick alone, and several detents landing between two passes arrive together.  A loop that stalled for a socket read and came back to a shaft someone had spun seven clicks reports `delta` of 7 on one tick rather than seven ticks of 1:

```python
if volume.just_moved:
    level += volume.delta       # the whole spin, in one go
```

`position` is a plain attribute you can write as well as read, which is how a value saved at shutdown goes back where it was:

```python
volume.position = saved_volume
```

Most panel-mount encoders click once per pulse cycle, and `detent_steps` defaults to `4` to match, so one click of the shaft moves `position` by one.  `DEFAULT_DETENT_STEPS` carries that number, and it is the same default CircuitPython's own `rotaryio.IncrementalEncoder` uses for its `divisor`.  A smooth encoder with no clicks in it wants `detent_steps=1`, which counts every pulse:

```python
smooth = Encoder(board.GP16, board.GP17, detent_steps=1)
```

## Holding the position inside a range

`bounds=(low, high)` is an inclusive range that `position` stays inside, so a volume knob walks 0 to 20 and settles at each end rather than running off into numbers your program has no use for:

```python
volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))
```

A knob held against a bound reports `delta` of 0 and `check()` returns False, so nothing downstream fires while the shaft keeps turning.  The turning that did not fit is dropped rather than banked, which means one detent back off the bound moves `position` by exactly one.  A range that does not contain zero starts at its nearer end: `bounds=(5, 9)` opens at 5.

`wrap=True` carries `position` around the range instead of settling at the ends, which is what a menu ring or a hue selector wants.  On `bounds=(0, 3)`, five detents forward from 0 land on 1:

```python
menu = Encoder(board.GP16, board.GP17, bounds=(0, 3), wrap=True)
```

Wrapping needs a range to wrap inside, so `wrap=True` without `bounds` raises `ValueError` at construction rather than behaving oddly later.

## An analog knob

Wire the potentiometer's outer legs to 3V3 and GND, and its wiper to an analog-capable pin such as `board.A0`.  `steps` is how many positions a full sweep reports, and `value` runs from 0 at one end to `steps - 1` at the other:

```python
import board
from chumicro_knobs import AnalogKnob
from chumicro_timing import ticks_ms

brightness = AnalogKnob(board.A0, steps=10)

while True:
    now = ticks_ms()
    brightness.check(now)

    if brightness.just_moved:
        print("brightness", brightness.value)     # 0 through 9
```

`steps` defaults to 100, held in `DEFAULT_STEPS`, which puts the middle of the sweep at 50 and the top at 99.  `delta` is the change for this tick, negative when the knob comes back down, and `raw` is the settled reading on the 0 to 65535 scale that `value` was worked out from:

```python
print(brightness.value, brightness.delta, brightness.raw)
```

Every runtime reports a conversion on that same 0 to 65535 scale whatever the converter's native width is, so a 12-bit part on an RP2040 and a wider part elsewhere read through identical code.  `RAW_RANGE` is that scale, 65536, and the next section puts it to work.

## The deadband

An analog reading wanders.  The low bits of a 12-bit converter move a couple of counts with the wiper parked, which is 32 counts once the reading is scaled to 16 bits, and a noisier part on a long lead moves several times that.  `deadband` is how far the raw reading has to move before `value` is allowed to follow it, and it defaults to 512, held in `DEFAULT_DEADBAND`:

```python
brightness = AnalogKnob(board.A0, steps=10, deadband=512)     # the default
```

512 sits well above the wander and well under the width of one step, so a parked wiper reports the same number pass after pass and every step is still reachable.  One step spans `RAW_RANGE // steps` counts, which is 655 at the default 100 steps:

```python
from chumicro_knobs import DEFAULT_STEPS, RAW_RANGE

step_width = RAW_RANGE // DEFAULT_STEPS      # 655
```

Keep `deadband` under that width.  A deadband two steps wide reports 2, 4, 6, 8 as a ten-step knob sweeps up and passes over the odd steps entirely, and a wide deadband also shortens the reachable ends of the sweep, where a pot that stops a few hundred counts short of the rail may never report step 0 again.  A finer sweep therefore wants a tighter deadband:

```python
fine = AnalogKnob(board.A1, steps=256, deadband=128)
```

`deadband=0` follows every sample, which is the setting for a signal that arrives clean already, from a filtered supply or a part with its own smoothing.

One detail worth knowing when you watch these attributes: a move that clears the deadband updates `raw` even when the step it lands in is the one `value` already held.  `just_moved` reports on `value`, so it stays false on that tick and no callback fires.

## Callbacks

If you would rather be called than ask, set `on_change` and let `handle(now_ms)` dispatch it:

```python
volume.on_change = lambda detents: print("moved", detents)
brightness.on_change = lambda step: print("brightness", step)

while True:
    now = ticks_ms()

    if volume.check(now):
        volume.handle(now)
    if brightness.check(now):
        brightness.handle(now)
```

`check()` returns True when the tick produced anything, which is the gate `handle()` sits behind.

Each callback takes one argument, and the argument follows the reading each device publishes.  The encoder hands you the signed detent change for the tick, so a handler adds it to something.  The analog knob hands you the step it now points at, so a handler uses it directly:

```python
def set_volume(detents: int) -> None:
    """Move the amplifier by however many clicks the shaft turned."""
    amplifier.adjust(detents)


def set_brightness(step: int) -> None:
    """Take the screen straight to the step the knob is pointing at."""
    screen.set_level(step)
```

Your callbacks run in your own loop, in normal context, so they can allocate, print, and raise like any other code.

## Giving the pins back

`deinit()` releases the pins a knob claimed, and on MicroPython it also lifts the interrupt off them so nothing counts afterwards:

```python
volume.deinit()
brightness.deinit()
```

A program that builds its knobs at startup and runs forever never reaches for this.  One that rebuilds them, say a device that repurposes the same encoder when it changes mode, calls `deinit()` before building the replacement.

## Runner pattern

`check(now_ms)` and `handle(now_ms)` are the contract [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) expects, so a knob joins the rest of your services with one line:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(wifi)
runner.add(volume)                          # checked every tick, handled when it has news
runner.add(brightness, period_ms=20)        # fifty samples a second is faster than a hand

while True:
    now = runner.tick()
    runner.wait(now)
```

The runner captures one timestamp per pass and shares it with everything, so a knob's idea of "now" matches the rest of the program.  The encoder belongs on every tick, since its `check()` is an attribute read and a subtraction.  An analog conversion costs more than that, and `period_ms` spaces those conversions out while still keeping up with any hand on the knob.

## Memory notes

`check()` allocates nothing in steady state.  The readings are plain attributes written in place, and each source publishes its count as an attribute rather than through a call that builds a value.  A program can tick a knob forever without the heap growing.

The MicroPython encoder source holds a three-slot `array.array` sized when the knob is built, registers one bound handler once, and keeps its decode table in flash as `bytes`, so a pulse arriving mid-tick writes small integers into slots that already exist.  Each pulse folds straight into the count, so those three integers are the whole of what the source keeps and there is nothing here for you to size.

## Testing

`chumicro_knobs.testing` stands in for the hardware, so knob logic is an ordinary unit test with no board and no shaft to wear out:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource


def test_the_volume_knob_stops_at_the_top():
    source = FakeEncoderSource()
    volume = Encoder(source=source, bounds=(0, 10))

    source.turn(25)
    volume.check(0)

    assert volume.position == 10
```

Turns queued before a single `check()` add up, which is how a test covers the fast spin during a stalled loop.  `FakeAnalogSource` does the same job for a potentiometer, with `set_raw()` parking the wiper wherever the test wants it.  The [testing page](testing.md) goes further, including the deadband and what the fakes record.

## Platform notes

The API is identical on all three runtimes.  What changes underneath is how the turning gets counted:

| Runtime | Rotary encoder | Analog knob |
|---|---|---|
| CircuitPython | `rotaryio.IncrementalEncoder`, counting in the firmware's own C, which on RP2040 is a state machine in the PIO block | `analogio.AnalogIn`, sampled on the tick that asks |
| MicroPython | A pin interrupt on both signal pins, installed and owned by the library, decoding the pulse pattern with a small table | `machine.ADC.read_u16()`, sampled on the tick that asks |
| CPython | No GPIO exists, so `pin_a=` raises and points you at `FakeEncoderSource` | No GPIO exists, so `pin=` raises and points you at `FakeAnalogSource` |

Counting an encoder outside the loop is what keeps a spin whole across a slow pass, and it is set up for you on both device runtimes.  An analog knob is sampled on the tick that asks for it on every runtime, because a voltage is whatever it is at the instant it is read, with no edge that could go by unseen.

On CircuitPython the modules this builds on (`rotaryio`, `analogio`) are compiled into the firmware, so they cost nothing in your board's storage.  One detail there is worth knowing before you pick pins: on RP2040 boards `rotaryio` reads both signal pins with one PIO state machine, which requires them to be next to each other in GPIO numbering, so `board.GP16` and `board.GP17` work together while `board.GP16` and `board.GP20` do not.  Other CircuitPython ports and every MicroPython port take any two pins.

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/circuitpython_encoder_volume.py) | An encoder for volume and a potentiometer for brightness on CircuitPython (hardware) |
| [`micropython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/micropython_encoder_volume.py) | The same two knobs on MicroPython (hardware) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
