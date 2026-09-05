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

## The GC9A01A round TFT in full color

`GC9A01A` drives the 240x240 round color TFT over SPI at 16-bit depth
with raw `color565` values.  It owns a full RGB565 frame (115,200
bytes), so it wants a PSRAM-class board on MicroPython, where `frame`
is a `framebuf.FrameBuffer`; on CircuitPython `frame` is a
`displayio.Bitmap` for `bitmaptools` to draw on, and the Pico W's
larger heap holds it.  The app constructs the bus and pins and injects
them; the driver never imports `machine` or `busio`:

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

## The portable canvas: the round TFT on both runtimes

`GC9A01AIndexed` is the panel whose drawing code runs unchanged on
MicroPython and CircuitPython.  Colors are palette indexes: assign an
index a color with `set_color`, then draw with the index, and `frame`
answers framebuf's method names on both runtimes: `fill`, `pixel`,
`hline`, `vline`, `line`, `rect`, `fill_rect`, `ellipse`, `poly`,
`blit`, `text`.  The frame is one byte per pixel (57,600 bytes) plus
a 256-entry palette on both runtimes, so a Pico W heap fits it under
either, and each flush advance expands one strip through the palette
in C before the strip crosses the bus:

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
from the next flush on, on both runtimes, which makes theme swaps and
blink effects one `set_color` call instead of a redraw.  Two
CircuitPython limits follow from what `bitmaptools` has a C path for: `ellipse`
draws unfilled circles only and `poly` outlines only, and the canvas's
own `text` renders the runtime's built-in font, whose metrics differ
from framebuf's 8x8; a converted font drawn through `Font` (below)
lands on the same pixels on both runtimes.  Construct the panel early:
the frame needs one contiguous block, which a fragmented heap may no
longer hold.

A flush sends only what changed.  The canvas records the rectangle
every primitive touched, and the flush sends the strips covering it,
each windowed to its columns, so an app that redraws a band of digits
pays a few advances rather than a frame.  The first flush after
construction sends the whole frame, and so does the flush after a
`set_color`, since drawn pixels holding the index change color.  Draw
the static parts once, then clear and redraw only what moves:

```python
frame.fill(BLACK)                          # once
frame.ellipse(120, 120, 118, 118, ACCENT)
frame.text("SECONDS", 92, 100, WHITE)

frame.fill_rect(92, 124, 56, 8, BLACK)     # every second
frame.text(str(seconds), 116, 124, WHITE)
screen.show()                              # two 6-row strips, not forty
```

Code that writes the frame's buffer directly marks its region with
`frame.dirty(x, y, width, height)`, and `frame.take_dirty()` is what
the flush reads.  On MicroPython the canvas is
`chumicro_screens.framebuf_canvas.FramebufCanvas`, a
`framebuf.FrameBuffer` subclass that also answers `width` and
`height`; each of its methods costs one Python frame and its
bookkeeping on top of the C primitive, about 110 us on an RP2040
against 28 us for a bare `pixel`, the same shape as the CircuitPython
canvas, so per-pixel loops belong in `blit` on both.

Measured on the Pi Pico W under MicroPython with the default 6-row
strip, where a whole frame is 40 advances at 3.2 ms mean and 3.6 ms
worst, 128 ms:

| Redraw | Strips | Advance mean | Advance worst | Flush |
|---|---|---|---|---|
| the counter's 56x8 band | 2 | 1.3 ms | 1.6 ms | 2.7 ms |
| a 16x16 notch | 4 | 0.6 ms | 1.0 ms | 2.6 ms |
| a 1-pixel column, top to bottom | 40 | 0.3 ms | 0.8 ms | 11.5 ms |
| a full-width 10-row band | 3 | 3.3 ms | 3.5 ms | 10.0 ms |
| a 200x120 region | 20 | 2.7 ms | 3.2 ms | 54 ms |
| nothing drawn | 0 | | | 0.4 ms |

A strip costs about 0.2 ms plus 2 us per pixel it carries, so a narrow
window shortens every advance as well as skipping strips.

The same redraws on the Pi Pico W under CircuitPython, first at the
default 8-bit frame and 3-row strip with black, white, and one accent
color (three passes), then at `frame_bits=16` with 6-row strips:

| Redraw | 8-bit strips | 8-bit flush | 16-bit strips | 16-bit flush |
|---|---|---|---|---|
| whole frame | 80 | 282 ms | 40 | 64 ms |
| the counter's 56x12 band | 5 | 13.5 ms | 3 | 4.1 ms |
| a 16x16 notch | 6 | 14.7 ms | 4 | 4.5 ms |
| a 1-pixel column, top to bottom | 80 | 169 ms | 40 | 33 ms |
| a 200x120 region | 40 | 135 ms | 20 | 34 ms |
| nothing drawn | 0 | 0.4 ms | 0 | 0.3 ms |

On the 8-bit frame the palette passes cover the strip's full width
whatever the window, so a narrow window saves the copy and the bus
but not the passes: the 1-pixel column still costs 2.1 ms a strip
against 3.5 ms at full width.  On the 16-bit frame each row of a
narrow window is its own bus write, about 0.1 ms, so a window wider
than about 160 pixels costs slightly more per strip than the full
width; the strip count is where that frame's saving is.

Bench datum from a Pi Pico W, whose `machine.SPI` clamps a 40 MHz
request to 24 MHz: the default 6-row strip measured 3.6 ms per
advance at worst and a full frame crosses in 40 advances, about
123 ms.  The strip size was fitted with a model of 0.2 ms fixed plus
0.5 ms per row, so taller strips barely shorten the frame; each row of
strip also costs 480 bytes of buffer on top of the frame.  Raise
`transfer_rows` only when your chip's own bench shows the headroom.

Under CircuitPython the expansion is a raw `bitmaptools.blit` of the
strip into a 16-bit strip bitmap and one `replace_color` pass per
assigned color, two for a color whose pre-swapped value is below 256
(pure red among them), so the advance grows with the palette.  Black
at index 0 needs no pass.  On the same Pi Pico W at the default 3-row
strip:

| Palette | Passes | Advance mean | Advance worst | Frame |
|---|---|---|---|---|
| black and white | 1 | 2.5 ms | 3.4 ms | 209 ms |
| black and four colors | 5 | 4.4 ms | 5.4 ms | 358 ms |
| black and seven colors | 9 | 6.1 ms | 6.9 ms | 492 ms |

Keep the palette to about five passes at 3 rows, or set
`transfer_rows=2` for more colors inside a 5 ms tick.  A pass rewrites
every pixel holding its index, so a strip solid in one color costs
each of its passes about 0.5 ms more than a mostly black one.
`frame_bits=16` holds a 16-bit frame (115,200 bytes) instead: no
expansion, a 6-row strip in 1.6 ms mean and 1.9 ms worst, 64 ms a
frame, but `set_color` applies to later drawing only.  On a Pico W
that frame only fits when it is allocated before anything else, ahead
of the driver's own compile: importing `chumicro_screens.gc9a01a`
leaves the heap's largest block at 115,072 bytes there, 128 short.
Allocate the bitmap first and hand it in:

```python
import displayio
frame_bitmap = displayio.Bitmap(240, 240, 65536)   # before any other import

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01AIndexed

panel = GC9A01AIndexed(spi, cs, dc, rst, frame_bits=16, bitmap=frame_bitmap)
```

That leaves a Pico W about 42 KB after the panel.  The
`gc9a01a_card.py` and `gc9a01a_counter.py` examples are one file each
and run on both runtimes.

## Fonts on the canvas

`chumicro_screens.fonts.Font` draws a proportional font on the canvas
with one call shape on both runtimes and lays the text out at the same
pixels on both.  The font is a module written on the host by
[font-to-py](https://github.com/peterhinch/micropython-font-to-py)
from a TrueType or OpenType file and shipped beside the app:

```bash
pip install font_to_py
font_to_py -x DejaVuSans.ttf 20 sans20.py
```

`-x` selects horizontal mapping, the layout both runtimes blit, and
`Font` refuses a vertically mapped module.  Construct the panel before
the font, so the frame gets the heap's largest block:

```python
import sans20
from chumicro_screens.fonts import Font

font = Font(sans20)
label = "12:34"
font.text(panel.frame, label, (panel.width - font.width(label)) // 2, 100, WHITE)
```

`text(canvas, string, x, y, index)` puts the first glyph's top-left at
(x, y) and draws only the glyphs' set pixels in the palette index, so
the canvas shows through the rest; `width(string)` is the pixels a
string spans; `height`, `baseline`, and `max_width` are the module's
metrics.  A character the module lacks draws as the glyph the module
substitutes, `?` unless it was converted with another.

Each runtime blits glyphs in C.  On MicroPython a glyph goes straight
from the module's buffer through a two-entry palette, so a font costs
its module and a few hundred bytes.  On CircuitPython the glyphs are
loaded once at construction into a 1-bit `displayio.Bitmap` sheet,
`height` rows of the glyph widths summed in bits (about 3 KB for a
20-pixel ASCII font), plus a 16-bit scratch bitmap the size of the
widest glyph.  `Font` targets `GC9A01AIndexed.frame`: on
MicroPython its palette is built for the 8-bit frame, so the 16-bit
`GC9A01A.frame` and the mono OLED are outside it.  The
`gc9a01a_font_counter.py` example centers a 20-pixel count on both
runtimes with `sans20.py`, its DejaVu Sans module.

Bench data from a Pi Pico W drawing the 7-glyph word "seconds" in
that font: MicroPython takes 4.0 ms mean and 4.2 ms worst per call,
0.57 ms a glyph, allocating 80 bytes a glyph inside the module's own
`get_ch`; CircuitPython takes 7.4 ms mean and 8.4 ms worst, 1.06 ms a
glyph, allocating nothing, and builds the sheet in 157 ms at
construction.  A `text` call is app redraw work rather than a tick,
but a long string on CircuitPython is worth splitting across passes
when the loop keeps a 5 ms budget.

## The round TFT through displayio

CircuitPython can also render the panel in firmware: `make_display`
feeds the panel's initialization sequence into `busdisplay.BusDisplay`
and displayio repaints changed regions in the background, which opens
its scene graph, `adafruit_display_text`, and the `gifio` and `jpegio`
decoders.  Pick this path for that ecosystem, and the canvas above for
a paced loop.  The repaint runs from
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
firmware's color converter handles the panel's byte order.  That
converter is also where the time goes: on a Pi Pico W a repaint costs
about 5.5 us per dirty pixel, so a 16x16 change is 1.7 ms and a
whole-screen change is 318 ms in one stall, automatic or from
`display.refresh()` alike.  Change small regions per tick, and let a
full redraw happen only where a third of a second of stall is
acceptable.

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
in 8 advances; a Pi Pico W measures the same page at 3.5 ms mean and
3.8 ms worst.  Four pages per advance costs 12.6 ms and one page at
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

Idle ticks allocate nothing: `check()` is comparisons only.  Starting a frame allocates one generator; the cost is per frame, not per tick, and only when `show()` was called.  Advancing a frame allocates nothing, and the drivers measure 0 bytes per advance on both runtimes.  A partial flush narrower than the frame adds one strip `FrameBuffer` and one view, about 100 bytes per frame, on MicroPython, whose `machine.SPI` writes whole buffers only; CircuitPython streams each row of a narrow window through `busio.SPI.write`'s `start` and `end` and adds nothing.  Finishing a frame allocates nothing on MicroPython, where the service reads the iterator's end through two-argument `next()`; CircuitPython board builds leave that form out, so there a finished frame costs one `StopIteration`, about 96 bytes, per frame rather than per tick.

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

The service behaves identically on CPython, MicroPython, and CircuitPython.  Panel drivers are where the runtimes differ.  `GC9A01AIndexed` runs on both: its `frame` is a `FramebufCanvas` over framebuf on MicroPython and a `BitmapCanvas` over a `displayio.Bitmap` on CircuitPython, and both record the bounds the flush sends.  `GC9A01A` draws raw 16-bit color on both, `SSD1306` is MicroPython-only, and `gc9a01a_displayio.make_display` and `ssd1306_displayio.make_display` hand a panel to displayio on CircuitPython, where the firmware owns refresh with no service in the loop.  Hardware drivers are added per controller as each passes bench validation.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass, simulated on CPython |
| [`micropython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_gc9a01a_round.py) | A seconds counter on the round TFT, redrawn once a second while the loop stays live (MicroPython hardware) |
| [`gc9a01a_card.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_card.py) | A labeled color card to run first after wiring, one file for both runtimes through the portable canvas; each bar names its color, so swapped channels and rotated mounts are visible at a glance |
| [`gc9a01a_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_counter.py) | The seconds counter from a Pi Pico W through the portable canvas, one file for both runtimes |
| [`gc9a01a_font_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_font_counter.py) | The seconds counter in a 20-pixel proportional font from a font-to-py module (`sans20.py` beside it), centered with `font.width()`, one file for both runtimes |
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
