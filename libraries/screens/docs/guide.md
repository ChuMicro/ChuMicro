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
from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01A, color565

spi = spi_bus(1, sck=7, mosi=11, miso=3, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(12, value=1),   # CS
                digital_output(9, value=0),    # DC
                digital_output(5, value=1))    # RST
screen = ScreenService(panel, refresh_interval_ms=100)

panel.frame.fill(0)
panel.frame.text("hello", 100, 116, color565(255, 255, 255))
screen.show()
```

The numbers are MCU GPIO numbers, which `chumicro_compat.wiring`
resolves into `machine.SPI` and `machine.Pin` here and into `busio`
and `digitalio` objects on CircuitPython, so the CircuitPython
construction further down carries the same ones.  A driver takes any
SPI object with `write` and any callable pin, so a hand-built
`machine.SPI` and `machine.Pin(n, Pin.OUT)` work too.

`panel.frame` is a real `framebuf.FrameBuffer`, so all framebuf
drawing works at C speed.  Colors always come from `color565`: the
frame stores pixels in the panel's on-wire byte order, and a raw
RGB565 literal renders the wrong color.  Construction blocks 330 to
365 ms, depending on the board, for panel reset and init.  Each flush advance sends one
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
from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01AIndexed

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01AIndexed(spi,
                       digital_output(5, value=1),   # CS
                       digital_output(8, value=0),   # DC
                       digital_output(9, value=1))   # RST
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

Bench datum from a Pi Pico W, whose `machine.SPI` clamps a 40 MHz
request to 24 MHz: the default 6-row strip measured 3.6 ms per
advance at worst and a full frame crosses in 40 advances, about
123 ms.  The strip size was fitted with a model of 0.2 ms fixed plus
0.5 ms per row, so taller strips barely shorten the frame; each row of
strip also costs 480 bytes of buffer on top of the frame.  Raise
`transfer_rows` only when your chip's own bench shows the headroom.

## The round TFT on CircuitPython

CircuitPython renders displays in firmware, so the panel plugs into
displayio instead of ScreenService: `make_display` feeds the panel's
initialization sequence into `busdisplay.BusDisplay` and the firmware
repaints changed regions in the background.  That repaint runs from
the firmware's background hook and stalls the app loop for the whole
transfer, measured at 11.4 ms at worst on a 128x64 OLED at 400 kHz
and 29.8 ms at 100 kHz, so a 5 ms tick budget does not hold under
`auto_refresh`.  When the budget matters, pass `auto_refresh=False`
and call `display.refresh()` from a handler of your own, which moves
the transfer to a tick you choose.  The app owns the bus and injects
it:

```python
import displayio
import fourwire
from chumicro_compat.wiring import gpio_pin, spi_bus
from chumicro_screens.gc9a01a_displayio import make_display

displayio.release_displays()
spi = spi_bus(1, sck=7, mosi=11)
display = make_display(fourwire.FourWire(
    spi, command=gpio_pin(9), chip_select=gpio_pin(12),
    reset=gpio_pin(5), baudrate=40_000_000))

group = displayio.Group()
display.root_group = group   # build the scene with displayio
```

From there everything is standard displayio: bitmaps, palettes, tile
grids, and groups.  There is no byte-order trap on this path; the
firmware's color converter handles the panel's byte order.

## The SSD1306 mono OLED

`SSD1306` drives the 128x64 (or 128x32) monochrome OLED over I2C on
MicroPython.  The controller's page layout is framebuf's `MONO_VLSB`,
so `frame` draws straight into the bytes the panel reads, and each
flush advance sends `transfer_pages` pages as one windowed transfer:

```python
from chumicro_compat.wiring import i2c_bus
from chumicro_screens import ScreenService
from chumicro_screens.ssd1306 import SSD1306

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)                    # address=0x3D when the jumper is bridged
screen = ScreenService(panel, refresh_interval_ms=100)

panel.frame.fill(0)
panel.frame.text("hello", 0, 28, 1)
screen.show()
```

Colors are 0 (dark) and 1 (lit), and `set_contrast(value)` sets the
drive current, which is brightness on an emissive panel.  Bench datum
from a LOLIN S2 Mini at 400 kHz: one page per advance averages 3.7 ms
with a worst case of 3.9 ms, inside a 5 ms tick, and a frame crosses
in 8 advances.  Four pages per advance costs 12.6 ms and one page at
100 kHz costs 13.0 ms, both outside the budget, so a paced panel wants
a 400 kHz bus and the default `transfer_pages`.  An advance allocates
nothing: the buffer carries the panel's control byte ahead of every
page row, so a page leaves in one `writeto` on either I2C port.

## The mono OLED on CircuitPython

`ssd1306_displayio.make_display` hands the same panel to displayio,
with the monochrome parameters the firmware needs told:

```python
import displayio
import i2cdisplaybus
from chumicro_compat.wiring import i2c_bus
from chumicro_screens.ssd1306_displayio import make_display

displayio.release_displays()
i2c = i2c_bus(0, scl=35, sda=33, frequency=400_000)
display = make_display(i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C))
```

A `displayio.Bitmap` built with `value_count=2` and a two-entry
palette covers the panel, and `display.brightness` sets the drive
current.  The background-refresh stall described for the round TFT
was measured on this panel.

## Runner pattern

`ScreenService` implements `check(now_ms)` / `handle(now_ms)`, so it registers like any other service, and `next_deadline(now_ms)` lets `runner.wait()` sleep until the next flush is actually due:

```python
from chumicro_runner import Runner
from chumicro_screens import ScreenService

runner = Runner()
screen = ScreenService(panel)
runner.add(screen)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Draw and `show()` from any other handler; the screen service flushes on its own turns.

## Memory notes

Idle ticks allocate nothing: `check()` is comparisons only.  Starting a frame allocates one generator; the cost is per frame, not per tick, and only when `show()` was called.  Advancing a frame and finishing it allocate nothing: the service reads the iterator's end through a sentinel rather than catching `StopIteration`, and the MicroPython drivers measure 0 bytes per advance against the real `framebuf`.

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

The service behaves identically on CPython, MicroPython, and CircuitPython.  Panel drivers are where the runtimes differ: on MicroPython the framebuf drivers (`GC9A01A`, `GC9A01AIndexed`, `SSD1306`) page their frame across advances under ScreenService, while on CircuitPython `gc9a01a_displayio.make_display` and `ssd1306_displayio.make_display` hand the panel to displayio and the firmware owns refresh with no service in the loop.  Hardware drivers are added per controller as each passes bench validation.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass, simulated on CPython |
| [`micropython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_round.py) | A seconds counter on the round TFT, redrawn once a second while the loop stays live (MicroPython hardware) |
| [`micropython_gc9a01a_indexed.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_indexed.py) | The same counter from a Pi Pico W through the indexed driver (MicroPython hardware) |
| [`micropython_gc9a01a_card.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_card.py) | A labeled color card to run first after wiring; each bar names its color, so swapped channels and rotated mounts are visible at a glance (MicroPython hardware) |
| [`circuitpython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_gc9a01a_round.py) | A color card on the round TFT via displayio, with a blinking notch proving live refresh (CircuitPython hardware) |
| [`micropython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_ssd1306_counter.py) | A bordered seconds counter on the mono OLED, one page per loop pass (MicroPython hardware) |
| [`circuitpython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_ssd1306_counter.py) | A border and a growing bar on the mono OLED via displayio (CircuitPython hardware) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
