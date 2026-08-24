# User Guide

## Overview

A full display frame is often too big to send in one go: a mono OLED frame over I2C takes tens of milliseconds on the bus, which is several ticks' worth of loop time.  `ScreenService` paces the flush instead.  You draw, call `show()`, and the service advances the panel's flush one bounded bus transfer per tick, with a frame-rate floor so redraws never crowd out buttons, network, or sensors.  The panel underneath is duck-typed: anything with a `flush()` method that returns an iterator works.

## Getting started

```python
from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms

class ConsolePanel:
    """Pretend driver: one print stands in for one bus transfer."""
    def __init__(self):
        self.message = ""
    def flush(self):
        print("transfer 1:", self.message[:8])
        yield
        print("transfer 2:", self.message[8:])

panel = ConsolePanel()
screen = ScreenService(panel, refresh_interval_ms=50)

panel.message = "hello screens"
screen.show()

for loop_pass in range(4):
    now_ms = ticks_ms()
    if screen.check(now_ms):
        screen.handle(now_ms)
```

The first two passes each perform one transfer; the rest of the loop stays free.

## The panel protocol

A panel is any object with one method:

```python
def flush(self):
    """Return an iterator; each advance performs one bounded bus transfer."""
```

Write it as a generator: do a transfer, `yield`, do the next.  A frame with N transfers completes after N `handle()` calls.  The shapes that come up:

```python
class PagedPanel:
    """A frame in pages, one page per tick: the usual driver shape."""
    def flush(self):
        for page_index in range(8):
            if page_index > 0:
                yield
            self._write_page(page_index)

class SingleTransferPanel:
    """A frame small enough for one transfer, done in one tick."""
    def flush(self):
        self._write_frame()
        return
        yield

class BackgroundRefreshPanel:
    """The runtime refreshes in the background; flush just requests it."""
    def flush(self):
        self._request_refresh()
        return
        yield
```

The trailing `return` / `yield` pair keeps the method a generator while yielding zero times, so the whole flush lands in one `handle()`.

Keep each transfer bounded: one page, strip, or window per advance, sized so a single advance stays inside a few milliseconds on your bus.

## Pacing and the frame-rate floor

`refresh_interval_ms` is a floor between flush starts, counted from each start.  The default of 50 caps redraws at 20 frames per second; `0` starts a new flush on the first tick after every `show()`.

Two behaviors worth knowing:

- `show()` during an active flush marks the *next* frame.  The current frame always finishes; the fresh content flushes after the floor elapses.
- A panel error mid-flush propagates out of `handle()` and drops that frame.  The service goes idle; the next `show()` schedules a fresh flush.

## The GC9A01A round TFT

The first shipped driver: a 240x240 round color TFT over SPI, on
MicroPython.  It owns a full RGB565 frame buffer (115,200 bytes), so
it needs a PSRAM-class board.  The app constructs the bus and pins and
injects them; the driver never imports `machine`:

```python
from machine import SPI, Pin
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01A, color565

spi = SPI(1, baudrate=40_000_000, polarity=0, phase=0,
          sck=Pin(7), mosi=Pin(11), miso=Pin(3))
panel = GC9A01A(spi,
                Pin(12, Pin.OUT, value=1),   # CS
                Pin(9, Pin.OUT, value=0),    # DC
                Pin(5, Pin.OUT, value=1))    # RST
screen = ScreenService(panel, refresh_interval_ms=100)

panel.frame.fill(0)
panel.frame.text("hello", 100, 116, color565(255, 255, 255))
screen.show()
```

`panel.frame` is a real `framebuf.FrameBuffer`, so all framebuf
drawing works at C speed.  Colors always come from `color565`: the
frame stores pixels in the panel's on-wire byte order, and a raw
RGB565 literal renders the wrong color.  Construction blocks about
350 ms for panel reset and init.  Each flush advance sends one
10-row strip, measured at 3.3 ms average on a LOLIN S2 Mini at
40 MHz, and a full frame crosses in 24 advances.

## The round TFT on 256 KB boards

`GC9A01AIndexed` drives the same panel from boards whose heap cannot
hold a 115 KB frame.  The frame is one byte per pixel (57,600 bytes)
plus a 256-entry palette: assign an index a color with `set_color`,
then draw with the index.  Each flush advance expands one strip
through the palette with `FrameBuffer.blit`, which converts at C
speed, then sends it:

```python
from machine import SPI, Pin
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01AIndexed

spi = SPI(0, baudrate=40_000_000, polarity=0, phase=0,
          sck=Pin(6), mosi=Pin(7), miso=Pin(4))
panel = GC9A01AIndexed(spi,
                       Pin(5, Pin.OUT, value=1),   # CS
                       Pin(8, Pin.OUT, value=0),   # DC
                       Pin(9, Pin.OUT, value=1))   # RST
screen = ScreenService(panel, refresh_interval_ms=100)

BLACK, WHITE = 0, 1
panel.set_color(WHITE, 255, 255, 255)
panel.frame.fill(BLACK)
panel.frame.text("hello", 100, 116, WHITE)
screen.show()
```

Editing a palette entry recolors every drawn pixel holding that index
from the next flush on, which makes theme swaps and blink effects one
`set_color` call instead of a redraw.  Construct the panel early: the
frame needs one contiguous 57,600-byte block, which a fragmented heap
may no longer hold.

## The round TFT on CircuitPython

CircuitPython renders displays in firmware, so the panel plugs into
displayio instead of ScreenService: `make_display` feeds the panel's
initialization sequence into `busdisplay.BusDisplay` and the firmware
repaints changed regions in the background, inside the tick budget.
The app owns the bus and injects it:

```python
import board
import busio
import displayio
import fourwire
from chumicro_screens.gc9a01a_displayio import make_display

displayio.release_displays()
spi = busio.SPI(clock=board.IO7, MOSI=board.IO11)
display = make_display(fourwire.FourWire(
    spi, command=board.IO9, chip_select=board.IO12,
    reset=board.IO5, baudrate=40_000_000))

group = displayio.Group()
display.root_group = group   # build the scene with displayio
```

From there everything is standard displayio: bitmaps, palettes, tile
grids, and groups.  There is no byte-order trap on this path; the
firmware's color converter handles the panel's byte order.

## Runner pattern

`ScreenService` implements `check(now_ms)` / `handle(now_ms)`, so it registers like any other service, and `next_deadline(now_ms)` lets `runner.wait()` sleep until the next flush is actually due:

```python
from chumicro_runner import Runner
from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms

runner = Runner()
screen = ScreenService(panel)
runner.add(screen)

while True:
    now_ms = ticks_ms()
    runner.tick()
    runner.wait(now_ms)
```

Draw and `show()` from any other handler; the screen service flushes on its own turns.

## Memory notes

Idle ticks allocate nothing: `check()` is comparisons only.  Starting a frame allocates one generator; the cost is per frame, not per tick, and only when `show()` was called.

## Testing

`chumicro_screens.testing.FakePanel` counts flush starts, transfers, and completions, and can inject a bus fault mid-frame:

```python
from chumicro_screens import ScreenService
from chumicro_screens.testing import FakePanel
from chumicro_timing.testing import FakeTicks

panel = FakePanel(transfers_per_flush=4)
screen = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())

screen.show()
for tick in range(4):
    screen.handle(tick)

assert panel.flushes_completed == 1
```

[Testing Helpers](testing.md) covers the full hook set.

## Platform notes

The service behaves identically on CPython, MicroPython, and CircuitPython.  Panel drivers are where the runtimes differ: on MicroPython the framebuf drivers (`GC9A01A`, `GC9A01AIndexed`) page their frame across advances under ScreenService, while on CircuitPython `make_display` hands the panel to displayio and the firmware owns refresh with no service in the loop.  Hardware drivers are added per controller as each passes bench validation.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass, simulated on CPython |
| [`micropython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_round.py) | A seconds counter on the round TFT, redrawn once a second while the loop stays live (MicroPython hardware) |
| [`micropython_gc9a01a_indexed.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_indexed.py) | The same counter from a Pi Pico W through the indexed driver (MicroPython hardware) |
| [`circuitpython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_gc9a01a_round.py) | A color card on the round TFT via displayio, with a blinking notch proving live refresh (CircuitPython hardware) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
