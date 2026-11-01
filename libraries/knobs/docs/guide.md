# User Guide

## Overview

A rotary encoder reports turning as pulses on two signal pins.  The pulses arrive fast enough that a busy loop misses most of a quick flick.  A potentiometer gives a voltage that never sits exactly still, so a program that prints it raw reports movement on a knob nobody is touching.

`chumicro_knobs` counts the pulses and steadies the voltage.  `Encoder` reads a rotary encoder as a count of *detents*, the clicks felt as the shaft turns.  `AnalogKnob` reads a potentiometer or slider as a step number, out of a chosen number of steps.  `check(now_ms)` refreshes both.  Both publish `delta` and `just_moved`.  Both call an `on_change` callback from `handle(now_ms)`.

An encoder counts movement from wherever it started, so it publishes `position`.  A potentiometer points somewhere fixed along its travel, so it publishes `value`.

`Encoder.position` matches the `position` of CircuitPython's `rotaryio.IncrementalEncoder`.  `check()` keeps the `if position != last_position` bookkeeping.  `AnalogKnob.raw` is the `value` of `analogio.AnalogIn` after smoothing, and `AnalogKnob.value` is that reading cut into steps.

## Getting started

On a Pi Pico W, wire the encoder's two signal pins (often labelled CLK and DT) to GP16 and GP17, and its common pin to GND.  A module with a `+` pin gets that pin wired to 3V3.  The library switches on the pins' internal pull-ups.

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17)

while True:
    now = ticks_ms()
    volume.check(now)               # read how far the shaft turned; never waits

    if volume.just_moved:           # True on exactly one pass per change
        print("volume", volume.position)
```

`check(now_ms)` collects the turning since the last pass and adds it to `position`.  It never waits, so the rest of the loop keeps running between turns.

Under CircuitPython on a Pico, the two signal pins must sit next to each other in GPIO numbering, as GP16 and GP17 do ([Platform notes](#platform-notes)).  On an ESP32-S2 board, any two pins work, such as `board.IO16` and `board.IO17`.

On MicroPython, the two pins are GPIO numbers or `machine.Pin` objects:

```python
from machine import Pin

volume = Encoder(Pin(16), Pin(17))
```

Everything else on this page is the same on both runtimes.

## Reading the encoder

Every reading is a plain attribute that `check()` refreshes:

```python
volume.position       # detents counted so far
volume.delta          # detents this pass added to position
volume.just_moved     # True only on the pass position changed
```

`position` starts at zero, counts up as the shaft turns one way, and counts down as it turns the other.  Swapping the two pins reverses the direction.

`delta` is the turning for this pass alone.  Several detents that land between two passes arrive together.  A loop busy for a moment while the shaft spun seven clicks sees a `delta` of 7 on one pass instead of seven passes of 1:

```python
if volume.just_moved:
    level += volume.delta       # the whole spin, in one go
```

Assigning `position` restores a value saved before power-off:

```python
volume.position = saved_volume
```

## Matching your encoder's clicks

An encoder sends several electrical steps per click.  `detent_steps` says how many make one click.  The default is 4, held in `DEFAULT_DETENT_STEPS`, which suits most panel-mount encoders and matches the default `divisor` of `rotaryio.IncrementalEncoder`.  Many cheap encoder modules send 2 instead.

A wrong setting raises nothing and puts the count off by a steady factor.  A `position` that moves only on every other click comes from an encoder that sends 2 steps per click, which wants `detent_steps=2`.  A `position` that moves by two per click comes from an encoder that sends 4, set to 2.

To measure an encoder, count every step with `detent_steps=1`, turn the shaft exactly ten clicks, and divide:

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

counter = Encoder(board.GP16, board.GP17, detent_steps=1)

while True:
    counter.check(ticks_ms())
    print(counter.position)      # turn ten clicks, then read this
```

Forty means `detent_steps=4`, twenty means `2`, and ten means `1`.  With the right setting, every click moves `position` by exactly one.  A smooth encoder with no clicks wants `detent_steps=1`, which counts every step:

```python
smooth = Encoder(board.GP16, board.GP17, detent_steps=1)
```

A count that jumps around, instead of being off by a steady factor, points at the wiring.  On a module with a `+` pin, the module's pull-up resistors work only once that pin is powered.  One module tested with its `+` pin unwired dropped steps at random, turning a steady two per click into a mix of ones, twos, and threes.

## Holding the position inside a range

`bounds=(low, high)` keeps `position` inside a range, both ends included.  A volume knob walks from 0 to 20 and stays at each end:

```python
volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))
```

Turning further against an end reports a `delta` of 0 and makes `check()` return `False`, so nothing downstream fires while the shaft keeps turning.  The library drops the extra turning instead of saving it up, so one click back off the end moves `position` by exactly one.  A range that leaves out zero starts at its nearer end, so `bounds=(5, 9)` starts at 5.

`wrap=True` carries `position` round from one end to the other instead, which suits a menu or a colour wheel.  On `bounds=(0, 3)`, five clicks forward from 0 land on 1:

```python
menu = Encoder(board.GP16, board.GP17, bounds=(0, 3), wrap=True)
```

`wrap=True` without `bounds` raises `ValueError` at construction, since it has no range to wrap round.

## An analog knob

Wire the potentiometer's outer legs to 3V3 and GND, and its middle leg to an analog pin such as `board.A0` (GP26 on a Pi Pico W).  `steps` is how many positions its travel is divided into.  `value` runs from 0 at one end to `steps - 1` at the other:

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

`value` starts at 0 and jumps to wherever the knob already points, so the first pass usually prints a number.

`steps` defaults to 100, held in `DEFAULT_STEPS`, which puts the middle of the travel at 50 and the top at 99.  `delta` is the change on this pass, negative when the knob comes back down.  `raw` is the smoothed reading behind `value`:

```python
print(brightness.value, brightness.delta, brightness.raw)
```

Every runtime reports `raw` on the same 0 to 65535 scale, whatever the converter's own resolution.  A 12-bit converter on a Pico and a different one on an ESP32 therefore read through identical code.  `RAW_RANGE` holds 65536, one past the top of that scale.

## Callbacks

`handle(now_ms)` calls `on_change` when the last `check()` found a move:

```python
import board
from chumicro_knobs import AnalogKnob, Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17)
brightness = AnalogKnob(board.A0, steps=10)
volume.on_change = lambda detents: print("moved", detents)
brightness.on_change = lambda step: print("brightness", step)

while True:
    now = ticks_ms()

    if volume.check(now):
        volume.handle(now)
    if brightness.check(now):
        brightness.handle(now)
```

`check()` returns `True` when the pass produced a change for `handle()` to report.

Each callback takes one argument, which follows the reading each part publishes.  The encoder passes the signed number of clicks the shaft turned this pass, which a handler adds to something.  The analog knob passes the step it now points at, which a handler uses directly:

```python
def set_volume(detents: int) -> None:
    """Move the amplifier by however many clicks the shaft turned."""
    amplifier.adjust(detents)


def set_brightness(step: int) -> None:
    """Take the screen straight to the step the knob points at."""
    screen.set_level(step)
```

The callbacks run in the main loop, outside any interrupt, so they can allocate memory, print, and raise.

## Runner pattern

An `Encoder` and an `AnalogKnob` each have the `check(now_ms)` and `handle(now_ms)` methods a [`chumicro-runner` service](https://chumicro.com/ChuMicro/runner/stable/guide/#services) needs, so one line joins each knob to the rest of the program:

```python
import board
from chumicro_knobs import AnalogKnob, Encoder
from chumicro_runner import Runner

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))
brightness = AnalogKnob(board.A0, steps=10)
volume.on_change = lambda detents: print("volume", volume.position)
brightness.on_change = lambda step: print("brightness", step)

runner = Runner()
runner.add(volume, period_ms=20)            # read the encoder fifty times a second
runner.add(brightness, period_ms=20)        # and the potentiometer too

while True:
    now = runner.tick()
    runner.wait(now)
```

Turning a knob cannot wake `runner.wait()`, which wakes only for timers and sockets ([How `wait()` decides how long to sleep](https://chumicro.com/ChuMicro/runner/stable/guide/#how-wait-decides-how-long-to-sleep)).  `period_ms=20` makes each knob a job that comes due fifty times a second, faster than a hand turns.  Without a period, a knob is read only when something else wakes the runner.  A program with no other job never rests at all.  A program with one five-second job reads the knob every five seconds.

The encoder counts outside the loop and loses nothing between reads, so the period decides only how soon the program sees a turn.  The analog knob takes one reading per `check()`, so the period also spaces its readings out.

## Holding an analog reading still

An analog reading wanders further than a datasheet suggests.  A potentiometer on a Pi Pico W, its wiper parked at the top of its travel where a converter is noisiest, measured 1744 counts of spread.  One step spans 655 counts at the default settings.

The library smooths each reading in two stages before `deadband` sees it.  The first stage takes the middle of the last three readings.  A lone wild reading can never be the middle of three, so the stage throws it away instead of averaging it in.  An average handles that case badly.  Fed one full-scale reading, an averaged value walks almost three steps out and takes dozens of readings to come back, while the middle of three stays put.

The second stage blends each surviving reading into the one before it instead of replacing it.  The number `check()` works from then drifts smoothly instead of leaping between noise extremes.  The leaping matters more than how wide the noise is.  A leaping reading drags the deadband's starting point across a step boundary and back, while a smoothly drifting one stays on its side.

The middle of three does almost nothing for steady noise.  Blending cannot throw a bad reading away.  Together, the two stages took an untouched knob at the noisiest end of its travel from around 12000 reported moves in twenty seconds to none.  Both stages work on the readings the loop already takes.

The blend counts in readings rather than milliseconds.  A loop running flat out settles within a couple of milliseconds.  A deliberately slow loop takes longer to catch up with a fast turn.

`deadband` is how far the smoothed reading has to move before `value` follows it.  It defaults to 512, held in `DEFAULT_DEADBAND`:

```python
brightness = AnalogKnob(board.A0, steps=10, deadband=512)     # the default
```

512 sits under the width of one step, so every step stays reachable.  The smoothing underneath keeps a parked knob on one number.  A deadband measures from the last reading that cleared it, so on its own it would have to be wider than the reading's whole spread.  On the board measured above, no deadband is both that wide and narrower than a step.  One step spans `RAW_RANGE // steps` counts, which is 655 at the default 100 steps:

```python
from chumicro_knobs import DEFAULT_STEPS, RAW_RANGE

step_width = RAW_RANGE // DEFAULT_STEPS      # 655
```

A `deadband` wider than a step skips steps.  A deadband two steps wide reports 2, 4, 6, 8 as a ten-step knob sweeps up, missing the odd steps.  It also shortens the reachable ends of the travel, where a potentiometer that stops a few hundred counts short of the rail may never report step 0 again.  A finer sweep therefore wants a tighter deadband:

```python
fine = AnalogKnob(board.A1, steps=256, deadband=128)
```

`deadband=0` follows every reading, which suits a signal that arrives clean already, from a filtered supply or a part with its own smoothing.

A move that clears the deadband updates `raw` even when it lands in the step `value` already held.  `just_moved` reports on `value`, so it stays `False` on that pass and no callback fires.

## When an encoder count drifts

Turned at the speed a hand normally turns a knob, an encoder counts exactly.  Ten clicks out and ten back land on the starting number every time.  Spun hard, a cheap encoder starts to drift, and no software in the stack corrects it.

An encoder's contacts bounce the same way a button's do.  At speed, the bouncing produces steps that look like real ones.  CircuitPython's `rotaryio` sets no glitch filter on the RP2040 or the ESP32, so every edge reaches its counter.  The interrupt this library installs on MicroPython also sees every edge.  Both decoders reject changes a turning shaft cannot make, which catches noise that flips both pins at once.  Noise that looks like a single step gets counted.

`detent_steps` covers the common case.  The decoder banks part-way steps until a whole click is earned, so a shaft resting between clicks and rocking across one boundary counts nothing, however long it rocks.

A time-based filter would be the wrong fix, because a fast spin is made of short pulses too.  A window long enough to reject bounce at three thousand pulses a second would also reject the fast turning it is meant to protect.  A button's bounce and its presses sit far apart in time, which lets `settle_ms` separate them.  An encoder's bounce and its turning share one timescale.

An RC filter on each of the two signal lines fixes the drift:

```
CLK ──[ 10k ]──┬── to the pin
               │
             [10nF]
               │
              GND
```

The filter smooths over about 100 microseconds, far shorter than a real pulse and far longer than the bouncing.  Better encoder modules carry these parts already.  Cheap ones leave the pads empty.

On an ESP32-S2, a bare module with no smoothing measured the same under both runtimes:

- Normal turning was exact.  Ten clicks out and ten back gave twenty moves, each of a single step, ending on zero.
- Spun by hand at about 1000 clicks per second, far past the part's rating, the count drifted a few percent over roughly 230 clicks.  The direction of the error changed between runs.  An error that changes sign comes from the contacts rather than the counting.

A hand turning a knob stays far below that speed, so in practice an encoder counts what it is turned.  The drift matters only when a machine spins the shaft.

## Giving the pins back

On CircuitPython, `deinit()` releases the pins a knob claimed.  On MicroPython, it takes the encoder's interrupt off its pins, so nothing counts afterwards:

```python
volume.deinit()
brightness.deinit()
```

A program that builds its knobs at startup and runs forever never needs `deinit()`.  A program that rebuilds them, such as a device that gives the same encoder a new job when it changes mode, calls `deinit()` before building the replacement.

## Memory notes

`check()` allocates no memory once the program is running.  The readings are attributes updated in place.  Each source publishes its count as an attribute instead of through a call that builds a value.  A program can check a knob forever without the heap growing.

The MicroPython encoder keeps three small integers in an `array.array` made when the knob is built.  It registers its interrupt handler once and keeps its decoding table in flash as `bytes`.  A pulse arriving mid-pass writes into slots that already exist, so nothing here needs sizing.

## Testing

`chumicro_knobs.testing.FakeEncoderSource` stands in for the hardware, which makes knob logic an ordinary unit test with no board and no shaft to wear out:

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

Turns queued before a single `check()` add up, which is how a test covers a fast spin during a busy loop.  `FakeAnalogSource` does the same job for a potentiometer.  Its `set_raw()` parks the wiper wherever the test wants it.  The [testing page](testing.md) covers the deadband and what the fakes record.

## Platform notes

Program code is identical on all three runtimes.  Each runtime counts the turning its own way:

| Runtime | Rotary encoder | Analog knob |
|---|---|---|
| CircuitPython | `rotaryio.IncrementalEncoder`, counting in the firmware, with the chip's PIO hardware doing it on RP2040 boards | `analogio.AnalogIn`, read on the pass that asks |
| MicroPython | A pin interrupt on both signal pins, installed and owned by the library, decoding the pulses with a small table | `machine.ADC.read_u16()`, read on the pass that asks |
| CPython | No pins exist, so pins raise a `RuntimeError` that names `FakeEncoderSource` | No pins exist, so a pin raises a `RuntimeError` that names `FakeAnalogSource` |

Counting outside the loop keeps a spin whole across a slow pass.  The library sets that counting up on both board runtimes.  Every runtime reads an analog knob on the pass that asks, because a voltage has no edge that could slip by unseen.

CircuitPython builds `rotaryio` and `analogio` into the firmware, so they take no space on the board's drive.  On RP2040 boards such as the Pi Pico W, `rotaryio` reads both signal pins with one PIO state machine, a small programmable block on the chip.  That state machine needs the two pins next to each other in GPIO numbering, so `board.GP16` pairs with `board.GP17` and never with `board.GP20`.  Other CircuitPython boards and every MicroPython board take any two pins.

### An analog knob loses some travel on ESP32

A potentiometer across 3V3 sweeps its whole range on an RP2040 and loses part of it on an ESP32.  The runtime decides which part, because the two runtimes read the converter differently.  One potentiometer on one board, swapped between runtimes, measured:

| | Range reached | Steps of 100 |
|---|---|---|
| RP2040, either runtime | 615 to 65535 | 0 to 99 |
| ESP32-S2, CircuitPython | 1440 to 49787 | 2 to 75 |
| ESP32-S2, MicroPython | 3796 to 65508 | 5 to 99 |

CircuitPython converts the reading to millivolts through a calibration table, then scales it as though 3.3 V were full scale.  The calibration straightens out the converter's low end, so the bottom of the travel is accurate.  An ESP32 stops reading around 2.5 V, so the top quarter never arrives.  MicroPython scales the raw count straight onto 0 to 65535 instead.  Whatever saturates the converter becomes 65535, so the top arrives.  The converter's offset at the bottom goes uncorrected, so the first few steps never arrive.

Both limits come from the runtimes.  Adafruit's board guides put the ESP32-S2 and S3 ceiling near 51000 counts, or 2.57 V.  A CircuitPython bug report records 51157 on an S2 against a full 65535 on an RP2040.  The exact figures vary from chip to chip.

A reading that runs out stops dead instead of fading.  The last stretch of the knob's travel moves nothing, and nothing raises.

Each board needs its own measurement.  Turn the knob from end to end and watch `raw`.  The numbers it stops at are that board's range.  `value` maps the whole 0 to 65535 scale onto `steps`, so on a board that stops at 49787, `value` never reaches the top quarter of its steps.  A program that needs every step rescales `raw` across the measured range itself.  A divider that keeps the potentiometer inside the measured range removes the dead stretch at the end of the travel, at the cost of resolution.

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/circuitpython_encoder_volume.py) | An encoder sets a volume from 0 to 20 and a potentiometer sets a brightness from 0 to 9, on CircuitPython (needs a board) |
| [`micropython_encoder_volume.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/knobs/examples/micropython_encoder_volume.py) | The same program on MicroPython (needs a board) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
