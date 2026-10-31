# User Guide

## Overview

A knob tells your program where it has been turned to, and getting that from a pin takes more than one read.  A rotary encoder reports turning as pulses on two signal pins, arriving fast enough that a busy loop misses most of a quick flick.  A potentiometer gives a voltage that never sits exactly still, so a program that prints it raw reports a knob nobody is touching.

`chumicro_knobs` does that work.  `Encoder` reads a rotary encoder as a count of *detents*, the clicks you feel as the shaft turns.  `AnalogKnob` reads a potentiometer or slider as a step number, out of however many steps you ask for.  Both are refreshed by `check(now_ms)`, both publish `delta` and `just_moved`, and both can call a function for you from `handle(now_ms)`.

The main reading is named for what each part knows.  An encoder counts movement from wherever it started, so it publishes `position`.  A potentiometer points somewhere fixed along its travel, so it publishes `value`.

If you have used CircuitPython's `rotaryio.IncrementalEncoder`, `Encoder.position` is its `position`, and `check()` does the `if position != last_position` bookkeeping for you.  If you have used `analogio.AnalogIn`, `AnalogKnob.raw` is its `value` after smoothing, and `AnalogKnob.value` is that reading cut into steps.

## Getting started

On a Pi Pico W, wire the encoder's two signal pins (often labelled CLK and DT) to GP16 and GP17 and its common pin to GND.  If the module has a `+` pin, wire it to 3V3.  The pins' internal pull-ups are switched on for you.

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

`check(now_ms)` collects the turning since the last pass and adds it to `position`.  It never waits, so the rest of your loop keeps running between turns.

On a Pico the two signal pins must sit next to each other in GPIO numbering, as GP16 and GP17 do; [Platform notes](#platform-notes) explains why.  On an ESP32-S2 board any two pins work, such as `board.IO16` and `board.IO17`.

On MicroPython the two pins are GPIO numbers or `machine.Pin` objects, and everything else on this page reads the same:

```python
from machine import Pin

volume = Encoder(Pin(16), Pin(17))
```

## Reading the encoder

Every reading is a plain attribute that `check()` refreshes:

```python
volume.position       # detents counted so far
volume.delta          # detents this pass added to position
volume.just_moved     # True only on the pass position changed
```

`position` starts at zero, counts up as the shaft turns one way, and counts down as it turns the other.  If it counts the wrong way, swap the two pins.

`delta` is the turning for this pass alone, and several detents that land between two passes arrive together.  A loop that was busy for a moment while someone spun the shaft seven clicks sees `delta` of 7 on one pass, not seven passes of 1:

```python
if volume.just_moved:
    level += volume.delta       # the whole spin, in one go
```

You can also set `position`, which is how a value saved before power-off goes back where it was:

```python
volume.position = saved_volume
```

## Matching your encoder's clicks

An encoder sends several electrical steps per click, and `detent_steps` says how many make one click.  The default is 4, held in `DEFAULT_DETENT_STEPS`, which suits most panel-mount encoders and matches the default `divisor` of CircuitPython's `rotaryio.IncrementalEncoder`.  Many cheap encoder modules send 2 instead.

A wrong setting is quiet: nothing raises, and the count is off by a steady factor.  If `position` moves only on every other click, your encoder sends 2 steps per click and wants `detent_steps=2`.  If it moves by two per click, it sends 4 and you have it set to 2.

To measure yours, count every step with `detent_steps=1`, turn the shaft exactly ten clicks, and divide:

```python
counter = Encoder(board.GP16, board.GP17, detent_steps=1)

while True:
    counter.check(ticks_ms())
    print(counter.position)      # turn ten clicks, then read this
```

Forty means `detent_steps=4`, twenty means `2`, ten means `1`.  Set it, and every click moves `position` by exactly one.  A smooth encoder with no clicks wants `detent_steps=1`, which counts every step:

```python
smooth = Encoder(board.GP16, board.GP17, detent_steps=1)
```

A count that jumps around rather than being off by a steady factor is a wiring problem.  On a module with a `+` pin, the pull-up resistors on the module do nothing until that pin is powered, and on one module measured here leaving it unwired dropped steps at random, turning a steady two per click into a mix of ones, twos, and threes.

## Holding the position inside a range

`bounds=(low, high)` keeps `position` inside a range, both ends included, so a volume knob walks from 0 to 20 and stays at each end rather than running off into numbers your program has no use for:

```python
volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))
```

Turning further against an end reports `delta` of 0, and `check()` returns `False`, so nothing downstream fires while the shaft keeps turning.  The extra turning is dropped rather than saved up, so one click back off the end moves `position` by exactly one.  A range that does not include zero starts at its nearer end: `bounds=(5, 9)` starts at 5.

`wrap=True` carries `position` round from one end to the other instead, which is what a menu or a colour wheel wants.  On `bounds=(0, 3)`, five clicks forward from 0 land on 1:

```python
menu = Encoder(board.GP16, board.GP17, bounds=(0, 3), wrap=True)
```

`wrap=True` without `bounds` raises `ValueError` when you build the encoder, since there is no range to wrap round.

## An analog knob

Wire the potentiometer's outer legs to 3V3 and GND, and its middle leg to an analog pin such as `board.A0` (GP26 on a Pi Pico W).  `steps` is how many positions its travel is divided into, and `value` runs from 0 at one end to `steps - 1` at the other:

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

The first pass usually prints a number, as `value` starts at 0 and jumps to wherever the knob already points.

`steps` defaults to 100, held in `DEFAULT_STEPS`, which puts the middle of the travel at 50 and the top at 99.  `delta` is the change on this pass, negative when the knob comes back down, and `raw` is the smoothed reading `value` was worked out from:

```python
print(brightness.value, brightness.delta, brightness.raw)
```

Every runtime reports `raw` on the same 0 to 65535 scale, whatever the converter's own resolution, so a 12-bit converter on a Pico and a different one on an ESP32 read through identical code.  `RAW_RANGE` is that scale, 65536.

## Callbacks

If you would rather be called than ask, set `on_change` and let `handle(now_ms)` call it:

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

`check()` returns `True` when the pass produced a change, which is when `handle()` has something to do.

Each callback takes one argument, and it follows the reading each part publishes.  The encoder hands you how many clicks the shaft turned this pass, signed, so a handler adds it to something.  The analog knob hands you the step it now points at, so a handler uses it directly:

```python
def set_volume(detents: int) -> None:
    """Move the amplifier by however many clicks the shaft turned."""
    amplifier.adjust(detents)


def set_brightness(step: int) -> None:
    """Take the screen straight to the step the knob points at."""
    screen.set_level(step)
```

Your callbacks run in your own loop like any other code, so they can allocate, print, and raise.

## Runner pattern

`check(now_ms)` and `handle(now_ms)` are the two methods [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) calls on every service, so a knob joins the rest of your program with one line:

```python
from chumicro_runner import Runner

volume.on_change = lambda detents: print("volume", volume.position)
brightness.on_change = lambda step: print("brightness", step)

runner = Runner()
runner.add(wifi)
runner.add(volume, period_ms=20)            # read the encoder fifty times a second
runner.add(brightness, period_ms=20)        # and the potentiometer too

while True:
    now = runner.tick()
    runner.wait(now)
```

`runner.wait(now)` rests the CPU until the next job is due, and turning a knob cannot wake it.  `period_ms=20` makes each knob a job that comes due fifty times a second, which is faster than a hand turns.  Leave it off and a knob is read only when something else wakes the runner: in a quiet program with nothing else due, the loop never rests at all, and in one with a five-second job, the knob answers every five seconds.

The encoder loses nothing between reads, because the counting happens outside your loop, so the period decides only how soon you see a turn.  The analog knob takes one reading per `check()`, and the period also spaces those readings out.  The runner reads the clock once per pass and hands every service the same time, so a knob's idea of "now" matches the rest of the program.

## Holding an analog reading still

An analog reading wanders, and further than a datasheet suggests.  A potentiometer on a Pi Pico W, with its wiper parked at the top of its travel where a converter is noisiest, measured 1744 counts of spread, against the 655 counts one step spans at the default settings.

Two stages smooth the reading before `deadband` ever sees it, and they reject different things.

The first takes the middle of the last three readings.  A lone wild reading can never be the middle of three, so it is thrown away rather than averaged in.  Averaging handles that case badly: fed one full-scale reading, an averaged value walks almost three steps out and takes dozens of readings to come back, while the middle of three does not move at all.

The second blends each surviving reading into the one before it rather than replacing it, so the number `check()` works from drifts smoothly instead of leaping between noise extremes.  That matters more than how wide the noise is, because a leaping reading drags the deadband's starting point across a step boundary and back, and a smooth one does not.

Neither stage substitutes for the other.  The middle of three does almost nothing for steady noise, and blending cannot throw a bad reading away.  Together they took an untouched knob at the noisiest end of its travel from around 12000 reported moves in twenty seconds to none.  Neither takes extra readings; both work on the ones the loop already takes.

The blending counts in readings, not milliseconds, so a loop running flat out settles within a couple of milliseconds while a deliberately slow loop takes longer to catch up with a fast turn.

`deadband` is how far the smoothed reading has to move before `value` follows it.  It defaults to 512, held in `DEFAULT_DEADBAND`:

```python
brightness = AnalogKnob(board.A0, steps=10, deadband=512)     # the default
```

512 sits under the width of one step, so every step stays reachable, and the smoothing underneath is what keeps a parked knob on one number.  A deadband alone cannot do that on a noisy converter: it would have to be wider than the reading's whole spread, because it measures from the last reading that cleared it, and on the board measured above no setting is both that wide and narrower than a step.  One step spans `RAW_RANGE // steps` counts, which is 655 at the default 100 steps:

```python
from chumicro_knobs import DEFAULT_STEPS, RAW_RANGE

step_width = RAW_RANGE // DEFAULT_STEPS      # 655
```

Keep `deadband` under that width.  A deadband two steps wide reports 2, 4, 6, 8 as a ten-step knob sweeps up, skipping the odd steps entirely, and it also shortens the reachable ends of the travel, where a potentiometer that stops a few hundred counts short of the rail may never report step 0 again.  A finer sweep therefore wants a tighter deadband:

```python
fine = AnalogKnob(board.A1, steps=256, deadband=128)
```

`deadband=0` follows every reading, which suits a signal that arrives clean already, from a filtered supply or a part with its own smoothing.

When you watch these attributes, a move that clears the deadband updates `raw` even when it lands in the step `value` already held.  `just_moved` reports on `value`, so it stays `False` on that pass and no callback fires.

## When an encoder count drifts

Turned at the speed a hand normally turns a knob, an encoder counts exactly: ten clicks out and ten back land on the number they started from, every time.  Spun hard, a cheap one starts to drift, and nothing in the stack stops that.

An encoder's contacts bounce the same way a button's do, and at speed the bouncing produces steps that look like real ones.  Nothing filters them.  CircuitPython's `rotaryio` sets no glitch filter on either the RP2040 or the ESP32, so every edge reaches its counter, and the same is true of the interrupt this library installs on MicroPython.  Both reject changes a turning shaft cannot make, which catches noise that changes both pins at once but not noise that happens to look like a step.

`detent_steps` covers the common case.  Part-way steps are held until a whole click is earned, so a shaft resting between clicks and rocking back and forth across one boundary counts nothing, however long it rocks.

A time-based filter would be the wrong fix, because a fast spin is made of short pulses too.  A window long enough to reject bounce at three thousand pulses a second would also reject the fast turning it is meant to protect.  A button can use `settle_ms` because its bounce and its presses are far apart in time; for an encoder they are the same signal.

The fix that works is hardware, on each of the two signal lines:

```
CLK ──[ 10k ]──┬── to the pin
               │
             [10nF]
               │
              GND
```

That smooths over about 100 microseconds, far shorter than a real pulse and far longer than the bouncing.  Better encoder modules already carry these parts; cheap ones leave the pads empty.

Measured on a bare module with no smoothing, on an ESP32-S2 running each runtime in turn:

- Normal turning was exact.  Ten clicks out and ten back gave twenty moves, each of a single step, ending on zero.
- Spun by hand at about 1000 clicks per second, far past the part's rating, the count drifted a few percent over roughly 230 clicks.  The direction of the error changed between runs, and an error that changes sign comes from the contacts, not the counting.

Nobody turns a knob that fast on purpose, so in practice an encoder counts what you turn.  The drift matters only if something in your project spins a shaft rather than a wrist.

## Giving the pins back

`deinit()` releases the pins a knob claimed, and on MicroPython it also takes the interrupt off them so nothing counts afterwards:

```python
volume.deinit()
brightness.deinit()
```

A program that builds its knobs at startup and runs forever never needs this.  One that rebuilds them, say a device that gives the same encoder a new job when it changes mode, calls `deinit()` before building the replacement.

## Memory notes

`check()` allocates no memory once the program is running.  The readings are attributes updated in place, and each source publishes its count as an attribute rather than through a call that builds a value.  A program can check a knob forever without the heap growing.

The MicroPython encoder keeps three small integers in an `array.array` made when the knob is built, registers its interrupt handler once, and keeps its decoding table in flash as `bytes`.  A pulse arriving mid-pass writes into slots that already exist, so there is nothing here for you to size.

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

Turns queued before a single `check()` add up, which is how a test covers a fast spin during a busy loop.  `FakeAnalogSource` does the same job for a potentiometer, with `set_raw()` parking the wiper wherever the test wants it.  The [testing page](testing.md) goes further, including the deadband and what the fakes record.

## Platform notes

The code you write is identical on all three runtimes.  What changes is how the turning gets counted:

| Runtime | Rotary encoder | Analog knob |
|---|---|---|
| CircuitPython | `rotaryio.IncrementalEncoder`, counting in the firmware; on RP2040 boards the chip's PIO hardware does it | `analogio.AnalogIn`, read on the pass that asks |
| MicroPython | A pin interrupt on both signal pins, installed and owned by the library, decoding the pulses with a small table | `machine.ADC.read_u16()`, read on the pass that asks |
| CPython | No pins exist, so `pin_a=` raises and points you at `FakeEncoderSource` | No pins exist, so `pin=` raises and points you at `FakeAnalogSource` |

Counting an encoder outside the loop is what keeps a spin whole across a slow pass, and it is set up for you on both board runtimes.  An analog knob is read on the pass that asks on every runtime, because a voltage is whatever it is at the moment it is read, with no change that could slip by unseen.

On CircuitPython, `rotaryio` and `analogio` are built into the firmware, so they take no space on your board's drive.  On RP2040 boards such as the Pi Pico W, `rotaryio` reads both signal pins with one PIO state machine, a small programmable block on the chip, which needs the two pins next to each other in GPIO numbering: `board.GP16` and `board.GP17` work together, `board.GP16` and `board.GP20` do not.  Other CircuitPython boards and every MicroPython board take any two pins.

### An analog knob loses some travel on ESP32

A potentiometer across 3V3 sweeps its whole range on an RP2040 and loses part of it on an ESP32.  Which part depends on the runtime, because the two read the converter differently.  One potentiometer, one board, swapped between runtimes:

| | Range reached | Steps of 100 |
|---|---|---|
| RP2040, either runtime | 615 to 65535 | 0 to 99 |
| ESP32-S2, CircuitPython | 1440 to 49787 | 2 to 75 |
| ESP32-S2, MicroPython | 3796 to 65508 | 5 to 99 |

CircuitPython converts the reading to millivolts through a calibration table and then scales it as though 3.3 V were full scale.  The calibration straightens out the converter's low end, so the bottom of the travel is accurate, but an ESP32 stops reading around 2.5 V and the top quarter never arrives.  MicroPython scales the raw count straight onto 0 to 65535 instead, so whatever saturates the converter becomes 65535 and the top arrives, while the converter's offset at the bottom goes uncorrected and the first few steps do not.

Neither comes from this library, and the CircuitPython limit is already known: Adafruit's board guides put the ESP32-S2 and S3 ceiling near 51000 counts, or 2.57 V, and CircuitPython carries an open bug reporting 51157 on an S2 against a full 65535 on an RP2040.  The exact figures vary from chip to chip.

What catches people is that a reading that runs out does not fade, it stops.  The last stretch of the knob's travel moves nothing, the number sits still, and nothing raises.

Measure the board in front of you rather than trusting the table: turn the knob from end to end and watch `raw`.  The numbers it stops at are your range.  Then ask for the steps you can reach:

```python
volume = AnalogKnob(board.IO9, steps=75)      # an ESP32-S2 under CircuitPython
```

Or feed the potentiometer from a divider that keeps it inside the range you measured, which costs resolution and gives back a sweep where every step means something.

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
