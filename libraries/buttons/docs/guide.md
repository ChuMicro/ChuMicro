# User Guide

## Overview

A button is a pin that reads high or low.  Its contacts bounce when they meet, so one press reads as several.  A quick tap can come and go between two passes of the loop.  A program also wants "held for two seconds" as an event apart from "pressed".

`chumicro_buttons` debounces the pin, catches the quick tap, and times the hold.

- `Button` reads one button or switch.
- `Buttons` reads several buttons in one scan.
- `KeyMatrix` reads a keypad wired as rows and columns.

All three publish the same readings, so code written for one button works unchanged for twelve.

`check()` does the job of `adafruit_debouncer`'s `update()`, and `just_pressed` matches its `Button.pressed`.  `pressed` here is the held-down level instead, true for as long as the button is down.  `check()` also keeps the `lastDebounceTime` bookkeeping of Arduino's Debounce sketch.

## Getting started

Wire a momentary button from GP14 to GND on a Pi Pico W.  [Wiring a button](#wiring-a-button) shows why the button is the only part.

```python
import board
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

button = Button(pin=board.GP14, ticks=ticks)    # ticks: the clock it times presses with

while True:
    now = ticks_ms()
    button.check(now)               # collect what the button did; never waits

    if button.just_pressed:         # True on exactly one pass per press
        print("pressed")
```

`check(now_ms)` collects whatever the button did since the last pass and updates the readings.  It never waits, so the rest of the loop keeps running.  `ticks=ticks` hands the button the `chumicro_timing.ticks` clock module, which times long presses, repeats, and clicks.  The argument is required.

MicroPython has no `board` module, so a `machine.Pin` names the pin instead:

```python
from machine import Pin

button = Button(pin=Pin(14), ticks=ticks)
```

Everything else on this page is the same on both runtimes.

Any pin that can read with a pull-up works, which on a Pico W means every `GP` pin.  On an ESP32-S2 board, GPIO 14 works too (`board.IO14` on CircuitPython).  GPIO 0 there is the BOOT button already on the board.  A classic ESP32's GPIO 34 to 39 are input-only with no pull-ups, so a button needs another pin.

## Wiring a button

<img src="schematics/wiring-active-low.svg" alt="A momentary switch from a GPIO pin to ground, with the microcontroller's internal pull-up enabled" width="420">

`Button(pin=...)` switches on the pin's internal pull-up, which holds the pin high until the button pulls it to GND.  The button is the only part the circuit needs.  A pressed button reads low, which is why `active_low` defaults to `True`.

A button wired to 3V3 instead takes `active_low=False`, which switches on the pin's internal pull-down in place of the pull-up.  This circuit adds an external 10 kΩ pull-down as well:

<img src="schematics/wiring-active-high.svg" alt="A switch from a GPIO pin to 3V3 with a 10k pull-down resistor to ground" width="420">

The 10 kΩ pull-down draws 330 µA while the button is held.  That current matters on a battery only for a button held often.

## Reading the button

Every reading is a plain attribute that `check()` refreshes:

```python
button.pressed          # True while the button is down
button.just_pressed     # True only on the pass the press landed
button.just_released    # True only on the pass the release landed
button.held_ms          # how long it has been down, in milliseconds
```

The `just_` readings are true on exactly one pass of the loop.  Reading one leaves it set, so several places in the loop can read it on that pass.  The next `check()` clears it.

`held_ms` keeps the length of the press that just ended, so code that runs on release can ask how long the button was held.  It starts again from zero on the next press.

`pressed` is the reading for a switch that stays where it is set, such as a toggle switch, a reed switch on a door, or a slide switch picking a mode.  A switch uses the same `Button` object.  Its `just_` readings report when the switch moved.

## Long press, repeat, and clicks

Long press is on by default at half a second.  Repeat and click counting stay off until their settings are given:

```python
button = Button(
    pin=board.GP14,
    ticks=ticks,
    long_press_ms=500,      # 0 turns long press off
    repeat_ms=200,          # 0 turns auto-repeat off
    repeat_delay_ms=700,    # how long to hold before repeat starts
    click_ms=250,           # 0 turns click counting off
)
```

A long press fires once per press, when the hold reaches `long_press_ms`:

```python
if button.just_long_pressed:
    factory_reset()
```

Auto-repeat is what a held arrow key does.  After `repeat_delay_ms`, `just_repeated` comes true every `repeat_ms` until the button is released:

```python
if button.just_pressed or button.just_repeated:
    volume += 1
```

Each repeat is scheduled from when the last one was due, so a slow pass leaves the rhythm intact.  A long stall gives one catch-up repeat instead of a burst.

Click counting tells a single click from a double click.  After each release, the button waits `click_ms` for another press.  When none comes, `just_clicked` turns true and `click_count` holds the number of presses in the run:

```python
if button.just_clicked:
    if button.click_count == 1:
        send_status()
    elif button.click_count == 2:
        wake_screen()
```

A press still reports `just_pressed` straight away.  Click counting adds a later event and delays nothing.  A press held longer than `click_ms` counts as a hold, and the click count leaves it out.  A long press therefore never also arrives as a single click.

## Callbacks

`handle(now_ms)` calls a callback for each event the last `check()` found:

```python
import board
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

button = Button(pin=board.GP14, ticks=ticks, click_ms=250)
button.on_press = lambda: print("down")
button.on_long_press = lambda: print("held for half a second")
button.on_click = lambda count: print("clicked", count, "times")

while True:
    now = ticks_ms()
    if button.check(now):
        button.handle(now)
```

`check()` returns `True` when the pass produced an event for `handle()` to report.  `on_click` needs `click_ms` set, because click counting is off at the default of 0.  The callbacks run in the main loop, outside any interrupt, so they can allocate memory, print, and raise.

## Several buttons

`Buttons` reads a group of buttons in one scan.  One scan costs less than one per button, and two buttons pressed together land on the same pass:

```python
import board
from chumicro_buttons import Buttons
from chumicro_timing import ticks, ticks_ms

buttons = Buttons(pins=(board.GP14, board.GP15, board.GP16), ticks=ticks)

while True:
    now = ticks_ms()
    buttons.check(now)

    if buttons[0].just_pressed:
        print("first button")

    if buttons[1].pressed and buttons[2].pressed:
        print("both held together")
```

Each `buttons[index]` is a `Button` with its own readings and callbacks, numbered in pin order.  `Buttons` also has group callbacks that receive the button's number, for one handler covering the whole group:

```python
buttons.on_press = lambda key_index: print("button", key_index, "down")
```

## A keypad matrix

A keypad wires its keys as a grid of rows and columns, so twelve keys need seven pins instead of twelve.  `KeyMatrix` reads that grid and hands back the same `Button` objects.  It lives in its own module, `chumicro_buttons.matrix`, which stays off boards that only have separate buttons:

```python
import board
from chumicro_buttons.matrix import KeyMatrix
from chumicro_timing import ticks, ticks_ms

keypad = KeyMatrix(
    row_pins=(board.GP2, board.GP3, board.GP4, board.GP5),
    column_pins=(board.GP6, board.GP7, board.GP8),
    ticks=ticks,
)

while True:
    now = ticks_ms()
    keypad.check(now)

    if keypad[0].just_pressed:
        print("top-left key")
```

Keys are numbered across each row in turn, so the key at `row`, `column` is `row * len(column_pins) + column`.  With the three columns above, key 4 is row 1, column 1.

CircuitPython scans the grid in the background, so a tap between two passes of the loop still lands.  MicroPython scans the grid once per `check(now_ms)`, because a grid has to be driven a row at a time.  A loop that stalls for long stretches can therefore miss a very short tap on a MicroPython matrix key.  Separate buttons catch every tap on both runtimes.

### Wiring the keypad

A ready-made membrane keypad brings its grid out as one row of header pins, rows and columns mixed.  Each header pin goes to a board pin that can both read with a pull-up and drive an output.  Every `GP` pin on a Pico W qualifies.  A classic ESP32's GPIO 34 to 39 can do neither.  On MicroPython, the pins are `machine.Pin` objects, as for a single button.

A membrane keypad has no diodes inside, so its rows and columns are interchangeable.  The choice of which pins are rows decides only which way the numbering runs.  A keypad that numbers its keys down the columns wants its two tuples swapped instead of rewired.

To map an unlabelled header, press each key in reading order and note which two pins connect.  The pin shared by every key in the first row is the first row pin.  The pins it pairs with are the column pins, in order.

On a grid without diodes, three pressed keys at three corners of a rectangle make the fourth corner read as pressed too.  The wiring causes this ghost key, which is why keyboards built for chords carry a diode per key.  On a grid with diodes, `columns_to_anodes` tells the scan which way they face.  It stays `True` when each diode's striped end points at a row pin.  A wrong setting damages nothing.  A diode keypad that reports no keys at all needs the setting flipped.

## Runner pattern

A `Button` has the `check(now_ms)` and `handle(now_ms)` methods a [`chumicro-runner` service](https://chumicro.com/ChuMicro/runner/stable/guide/#services) needs, so one line joins it to the rest of the program:

```python
import board
from chumicro_buttons import Button
from chumicro_runner import Runner
from chumicro_timing import ticks

button = Button(pin=board.GP14, ticks=ticks)
button.on_press = lambda: print("pressed")
button.on_long_press = lambda: print("held for half a second")

runner = Runner()
runner.add(button, period_ms=20)    # look at the button every 20 ms

while True:
    now = runner.tick()
    runner.wait(now)
```

The runner calls `handle()` only on passes where `check()` found an event, so a program built on callbacks never reads the `just_` readings itself.

A press is a change on a pin, and `runner.wait()` wakes only for timers and sockets ([How `wait()` decides how long to sleep](https://chumicro.com/ChuMicro/runner/stable/guide/#how-wait-decides-how-long-to-sleep)).  `period_ms=20` makes the button a job that comes due every 20 ms, which caps how long a press waits to be reported.  Without a period, the button is checked only when something else wakes the runner.  In a busy program that happens constantly.  In a quiet program with one five-second job, it happens every five seconds.

A press that lands while the runner rests is still captured with its real time ([Presses land even when the loop is slow](#presses-land-even-when-the-loop-is-slow)).  The period decides how soon the program hears about a press, never whether it does.  A press during another service's slow `handle()`, such as a network handshake, is captured the same way, and its callback runs on the pass that follows.  Long presses, repeats, and the end of a click run are checked on the same 20 ms schedule, so each fires within 20 ms of when it is due.

## Tuning the debounce

A small tactile button's contacts settle in one to five milliseconds.  A bigger toggle switch or microswitch can take twenty.  `settle_ms` sets the debounce window, 10 ms by default:

```python
button = Button(pin=board.GP14, ticks=ticks, settle_ms=10)   # the default
button = Button(pin=board.GP14, ticks=ticks, settle_ms=20)   # a switch that bounces badly
button = Button(pin=board.GP14, ticks=ticks, settle_ms=0)    # the signal is already clean
```

A change counts once the pin has held its new level for `settle_ms`.  `settle_ms` is also the shortest press the library can report.  A tap shorter than the window never holds its new level long enough to count.  The library throws it away with the bounce and reports nothing.

On a Pi Pico W with a button that has no debounce hardware, 30 seconds of tapping as fast as a finger goes closed the contacts 107 times.  Thirty of those taps were shorter than 20 ms, and seven were shorter than 10 ms.  A 20 ms window would have dropped more than a quarter of them.  The 10 ms default drops about six in a hundred.  That measurement set the default at 10.

| `settle_ms` | Good for | Drops taps shorter than |
|---|---|---|
| 20 | A toggle, a microswitch, or any big switch that bounces badly | 20 ms, about a quarter of fast tapping |
| 10 (default) | A tactile button, which is most buttons | 10 ms, about six taps in a hundred |
| 5 | Fast tapping or a game control, on a measured button | 5 ms, which a finger rarely reaches |
| 0 | Debouncing hardware behind the pin, or a signal already clean | nothing |

On a big switch, a gap of more than 10 ms in the middle of the bouncing can count as a real change.  A 20 ms window covers that gap.

### Adding a capacitor

Software debouncing serves almost every project.  A capacitor at the pin earns its place when the wire to the button is long enough to pick up noise, or when the button also feeds another circuit.

<img src="schematics/debounce-rc.svg" alt="A 10k pull-up, a 2.2k series resistor, and a 2.2uF capacitor forming an RC filter into a GPIO pin" width="480">

The capacitor slows both edges, so the bouncing never reaches the pin.  It empties through the series resistor alone, which takes 4.8 ms on a press.  It refills through the pull-up, which takes 27 ms on a release.

The series resistor limits the current through the contacts when the capacitor empties into them.  It also has to stay well below the pull-up, because the pin's internal pull-up is still switched on and forms a divider with it.  At 2.2 kΩ, the pressed pin sits near 0.5 V, a solid low.  At 10 kΩ it would sit near 1.4 V, too high to read as low.

With the capacitor in place, `settle_ms=5` suits the button.  Zero is too low.  A plain input pin switches at one threshold with no reliable margin, so a slow edge can still flicker as it passes through.  The settle window catches that flicker.  A bigger capacitor makes the flicker worse, because the edge spends longer near the threshold.

## Presses land even when the loop is slow

A program busy with a network request or a flash write reads a plain pin too late, and a tap in between is gone.  This library captures the press when it happens.  On CircuitPython, the firmware's background scan captures it.  On MicroPython, a small pin interrupt the library installs captures it.  Capture needs no setup and has no mode to choose.

Durations count from the real press:

```python
button.check(now)
if button.just_pressed:
    print(button.held_ms)      # already above zero if your loop was busy
```

A press at 100 ms that a busy loop notices at 180 ms reports 80 ms held instead of 0.

When a signal is so noisy that capture cannot keep up, `button.overflowed` comes true for that pass.  An ordinary button never trips it.  A button that does trip it needs the capacitor from [Adding a capacitor](#adding-a-capacitor).

## Memory notes

`check()` allocates no memory once the program is running.  Presses arrive through a buffer made when the button is built.  The readings are attributes updated in place, and the loops count by hand instead of building iterators.  A program can check a button forever without the heap growing.

On MicroPython, the button sizes its capture buffer at construction to hold the burst of edges a bouncing contact produces.  `overflowed` reports a burst bigger than that.

## Testing

`chumicro_buttons.testing.FakeButtonSource` stands in for the hardware, which makes press logic an ordinary unit test with no board and no waiting:

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_hold_arms_the_reset():
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=3000)

    source.press(at_ms=100)
    button.check(100)
    button.check(3200)

    assert button.just_long_pressed
```

Each queued press or release carries its own `at_ms`, separate from the time passed to `check()`.  That gap is how a test covers a slow loop on a laptop.  The [testing page](testing.md) covers two buttons pressed together and the overflow case.

## Platform notes

| Runtime | How presses are captured |
|---|---|
| CircuitPython | The firmware's `keypad` module, which scans in the background and stamps each press with the time it happened |
| MicroPython | A pin interrupt the library installs and owns.  Callbacks never run inside it |
| CPython | No pins exist, so `pin=` raises a `RuntimeError` that names `FakeButtonSource` |

Program code is identical on all three runtimes.  CircuitPython builds the `keypad` module into the firmware, so it takes no space on the board's drive.

## Examples

| Example | What it shows |
|---|---|
| [`circuitpython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/circuitpython_button_toggle.py) | A press flips the onboard LED and a half-second hold turns it off, on CircuitPython (needs a board) |
| [`micropython_button_toggle.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/buttons/examples/micropython_button_toggle.py) | The same program on MicroPython (needs a board) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
