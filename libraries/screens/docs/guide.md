# User Guide

## Overview

A pixel panel over SPI or I2C holds its own picture, so `chumicro-screens` keeps no copy of it.  An app describes a scene of items (`Rect`, `Box`, `Line`, `Ring`, `Text`, `Sprite`) on a `Screen`, marks the items it changes, and `ScreenService` paints the strips those changes touch into one small buffer, a few rows tall, and sends each as one bus transfer per tick.  RAM is the strip plus the scene whatever the panel's size, no tick blocks on the bus, and a change to one label repaints the one or two strips under it.  The drawing runs through the runtime's own C primitives, `framebuf` on MicroPython and `bitmaptools` on CircuitPython, so one app file draws on both.

## Getting started

```python
from chumicro_compat.wiring import i2c_bus
from chumicro_screens import Box, Screen, ScreenService, Text
from chumicro_screens.ssd1306 import SSD1306
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)

LIT = 1
screen.add(Box(0, 0, 128, 64, LIT))
screen.add(Text(4, 8, "chumicro", LIT))
count = Text(4, 44, "0", LIT)
screen.add(count)
service.show()

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        count.string = str(seconds)
        screen.mark(count)
        service.show()
    if service.check(now_ms):
        service.handle(now_ms)
```

`add` puts an item on the scene and marks it, `mark` records a change, and `show()` tells the service a flush is due.  Each `handle()` then paints and sends one strip; the first frame takes eight of them on this panel, and every count after that takes two.

## The scene and its items

Items paint in the order added, so a later item covers an earlier one where they overlap.  Every item takes its pixel value as the panel stores it: 0 or 1 on the mono OLED, a `color565` value on the round TFT.

```python
from chumicro_screens import Box, Line, Rect, Ring, Sprite, Text

Rect(x, y, width, height, value)          # filled
Box(x, y, width, height, value)           # one-pixel outline
Line(x0, y0, x1, y1, value)               # both ends inclusive
Ring(x_center, y_center, radius, value)   # one-pixel circle
Text(x, y, string, value, font=None)      # built-in font, or a Font
Sprite(x, y, source, width, height, key)  # a bitmap, one value transparent
```

Change an item by setting its attributes and marking it.  A mark repaints where the item was and where it now is, so moving or shrinking an item leaves nothing behind, and `screen.remove(item)` repaints the space it held.  `screen.mark_all()` repaints the whole panel.

```python
count.string = "42"
count.x = (screen.width - font.width(count.string)) // 2
screen.mark(count)
```

`Text` without a font draws the runtime's built-in glyphs, 8 by 8 on MicroPython and `terminalio.FONT`'s 6 by 12 on CircuitPython, so a built-in label lands at the same position but a different size on the two runtimes.  A `Sprite`'s source is the runtime's own bitmap type: a `framebuf.FrameBuffer` or a `(buffer, width, height, format)` sequence on MicroPython, a `displayio.Bitmap` on CircuitPython.

## The GC9A01A round TFT

`GC9A01A` drives the 240x240 round color TFT over SPI on both runtimes.  The app constructs the bus and the three output pins and injects them; `chumicro_compat.wiring` resolves GPIO numbers into `machine` objects on MicroPython and `busio` and `digitalio` objects on CircuitPython, so one set of numbers serves both.  Colors come from `color565`, which packs a color into the panel's on-wire byte order; a raw RGB565 literal renders the wrong color.

```python
from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import Ring, Screen, ScreenService, Text
from chumicro_screens.gc9a01a import GC9A01A, color565

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(5, value=1),    # CS
                digital_output(8, value=0),    # DC
                digital_output(9, value=1))    # RST
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)

WHITE = color565(255, 255, 255)
screen.add(Ring(120, 120, 118, color565(255, 128, 0)))
screen.add(Text(92, 100, "SECONDS", WHITE))
service.show()
```

Construction blocks 330 to 365 ms for the panel's reset and initialization.  The strip is `rows` rows of RGB565, 8 by default, and an 8-row strip is 3,840 bytes.  Measured on a Pi Pico W with the counter scene above, a full paint of 30 strips takes 78 ms under MicroPython at 2.6 ms mean and 2.9 ms worst per strip, and 84 ms under CircuitPython at 2.8 ms and 3.7 ms; the count's two strips take 5 ms and 6 ms.  A card of eleven items paints at 2.9 ms and 3.6 ms mean.  Run `gc9a01a_card.py` first after wiring: each bar names its color, so swapped channels and rotated mounts show at a glance.

## Proportional fonts

`chumicro_screens.fonts.Font` wraps a module written on the host by [font-to-py](https://github.com/peterhinch/micropython-font-to-py):

```bash
pip install font_to_py
font_to_py -x DejaVuSans.ttf 20 sans20.py
```

`-x` selects horizontal mapping, the layout both runtimes blit, and `Font` refuses a vertically mapped module.  A `Text` item built with the font lands on the same pixels under MicroPython and CircuitPython, and `font.width()` centers it:

```python
import sans20
from chumicro_screens import Text
from chumicro_screens.fonts import Font

font = Font(sans20)
caption = "seconds"
screen.add(Text((screen.width - font.width(caption)) // 2, 84, caption, WHITE, font))
```

`height`, `baseline`, and `max_width` carry the module's metrics.  On MicroPython each glyph blits from the module's bytes on every paint, about 0.6 ms a glyph on a Pi Pico W; on CircuitPython the string renders into a sprite when it changes and blits in one call per strip.

## The SSD1306 mono OLED

`SSD1306` drives the 128x64 or 128x32 monochrome OLED over I2C on MicroPython.  The controller's page layout is framebuf's `MONO_VLSB`, so the strip is one page of eight rows over the bytes the bus sends, and a page leaves in one `writeto`:

```python
from chumicro_compat.wiring import i2c_bus
from chumicro_screens.ssd1306 import SSD1306

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)             # address=0x3D when the jumper is bridged
```

Pixel values are 0 for dark and 1 for lit, and `set_contrast(value)` sets the drive current, which is brightness on an emissive panel.  At 400 kHz a page crosses a Pi Pico W in 4.1 ms mean and 4.2 ms worst with the counter scene painted into it, a frame in 8 pages and 32 ms, and the count line in 2 pages and 8 ms; at 100 kHz a page takes 13 ms, so a panel sharing a tick budget wants the faster bus.  On CircuitPython the panel stays on displayio, below.

## Strips, the tick budget, and `rows`

Each advance clears the strip, paints every item whose bounds cross it, and sends it, so an advance costs the bus transfer plus one C call per item in the band.  The bus is about 2 ms for an 8-row strip of the round TFT at 24 MHz on an RP2040; on MicroPython a `framebuf` call is 60 to 370 us, and on CircuitPython `bitmaptools` costs about 0.7 us per pixel it touches for a fill and 1.5 us for a blit, so a 160-pixel-wide bar adds about 0.9 ms to each strip it crosses there.  `rows` is the one knob: fewer rows per strip shorten every advance and add advances to a frame.  A first paint is elapsed time across ticks, never a stall; the loop keeps running through it.

## The panel protocol

A panel for a `Screen` is three attributes and one method:

```python
class MyPanel:
    width = 160
    height = 80

    def __init__(self, bus):
        self.strip = ...                 # a FramebufStrip or BitmapStrip, rows tall

    def write_strip(self, top, count):
        """Send count rows of the strip to the panel rows from top, as one transfer."""
```

The strip is `chumicro_screens.framebuf_strip.FramebufStrip` over a `framebuf.FrameBuffer` you build in the panel's pixel format on MicroPython, or `chumicro_screens.bitmap_strip.BitmapStrip` on CircuitPython, whose `buffer` is the bytes to stream.  A panel with its own window write needs nothing else; `GC9A01A` and `SSD1306` are the two shapes.

`ScreenService` itself drives anything with a `flush()` that returns an iterator and performs one bounded transfer per advance, which is what `Screen.flush()` is.  A panel that manages its own frame can still implement `flush()` directly and skip the scene.

## Pacing

`refresh_interval_ms` is a floor between flush starts, counted from each start; the default of 50 caps redraws at 20 frames per second and `0` starts a flush on the first tick after every `show()`.  `show()` during an active flush marks the next frame, so a slow panel always finishes the frame it started.  A bus error mid-flush propagates out of `handle()` and drops the frame; the next `show()` schedules a fresh one.

## displayio on CircuitPython

`gc9a01a_displayio.make_display` and `ssd1306_displayio.make_display` hand a panel to displayio, where the firmware owns the picture and the refresh and the whole displayio ecosystem applies, with no service in the loop:

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
display.root_group = displayio.Group()
```

The refresh runs from the firmware's background hook and stalls the loop for the whole dirty area, about 5.5 us per pixel on a Pi Pico W: 1.7 ms for a 16x16 change, 318 ms for the whole round panel, and 11.4 ms at worst for the OLED at 400 kHz.  Pass `auto_refresh=False` and call `display.refresh()` from a handler of your own to choose the tick that pays it, and keep the changed region small when the budget matters.

## Runner pattern

`ScreenService` implements `check(now_ms)` / `handle(now_ms)`, so it registers like any other service, and `next_deadline(now_ms)` lets `runner.wait()` sleep until the next flush is due:

```python
from chumicro_runner import Runner
from chumicro_screens import Screen, ScreenService

runner = Runner()
screen = Screen(panel)
service = ScreenService(screen)
runner.add(service)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

Mark items and call `service.show()` from any other handler; the service flushes on its own turns.

## Memory notes

The strip is the only buffer: 3,840 bytes for the round TFT at 8 rows, 129 bytes for the OLED's page.  A scene is a handful of small objects; a `Ring` on CircuitPython adds its per-strip arcs, 848 bytes for the 118-pixel ring, and a `Text` there holds a sprite of its string in the strip's format.  Idle ticks allocate nothing.  A frame allocates its generator, 144 bytes on MicroPython and 176 on CircuitPython, and an advance allocates nothing on either runtime.  Rendering happens at mark time, so a `Text` mark on CircuitPython allocates the new sprite and a `Ring` mark that moved the ring recuts its arcs; a recolor does neither.

## Testing

`chumicro_screens.testing` ships `FakeScreenPanel`, a panel whose strip records every primitive call with the band it was painted in and whose `writes` lists every strip sent, and `FakePanel`, a flush-protocol fake for `ScreenService` alone:

```python
from chumicro_screens import Rect, Screen
from chumicro_screens.testing import FakeScreenPanel

panel = FakeScreenPanel(width=32, height=32, rows=8)
screen = Screen(panel)
screen.add(Rect(0, 10, 4, 4, 1))

flush = screen.flush()
for _ in flush:
    pass

assert panel.writes == [(8, 8)]
assert panel.strip.calls == [("clear", 8, 0), ("fill_rect", 8, 0, 10, 4, 4, 1)]
```

[Testing Helpers](testing.md) covers the full hook set.

## Platform notes

`Screen`, the items, and `ScreenService` behave identically on CPython, MicroPython, and CircuitPython; the strip is where the runtimes differ.  `GC9A01A` runs on both device runtimes over a `FramebufStrip` or a `BitmapStrip`.  `SSD1306` is MicroPython-only, and its CircuitPython counterpart is `ssd1306_displayio.make_display`, since nothing in `bitmaptools` packs the panel's vertical byte order.  `bitmaptools.draw_circle` moves a center outside the bitmap instead of clipping, which is why a `Ring` on CircuitPython is drawn as the arcs of a polygon per strip.  Drivers are added per controller as each passes bench validation.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass, simulated on CPython |
| [`gc9a01a_card.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_card.py) | A labeled color card to run first after wiring, one file for both runtimes; each bar names its color, so swapped channels and rotated mounts are visible at a glance |
| [`gc9a01a_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_counter.py) | A seconds counter on the round TFT, one file for both runtimes; each second marks one item and repaints two strips |
| [`gc9a01a_font_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_font_counter.py) | The counter in a 20-pixel proportional font from a font-to-py module (`sans20.py` beside it), centered with `font.width()`, one file for both runtimes |
| [`circuitpython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_gc9a01a_round.py) | A color card on the round TFT via displayio, with a blinking notch proving live refresh (CircuitPython hardware) |
| [`micropython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_ssd1306_counter.py) | A bordered seconds counter on the mono OLED, one page per loop pass (MicroPython hardware) |
| [`micropython_ssd1306_font_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_ssd1306_font_counter.py) | The mono OLED counter in a 20-pixel proportional font from `sans20.py`, repainting the pages under the count each second (MicroPython hardware) |
| [`circuitpython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_ssd1306_counter.py) | A border and a growing bar on the mono OLED via displayio (CircuitPython hardware) |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
