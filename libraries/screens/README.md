# chumicro-screens

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Pixel panels with no frame in RAM and no tick on the bus.**

Describe a scene of items, mark what changed, and the flush paints the strips those changes touch into one small buffer and sends each as one bus transfer per tick.  RAM is the strip plus the scene whatever the panel's size, and one app file draws on MicroPython and CircuitPython through each runtime's own C primitives.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_screens

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_screens

# CPython
pip install chumicro-screens
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_screens import Rect, Screen, ScreenService, Text
from chumicro_screens.testing import FakeScreenPanel
from chumicro_timing import ticks_ms

panel = FakeScreenPanel(width=32, height=32, rows=8)   # any panel: a strip and write_strip()
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=50)

label = Text(2, 12, "hi", 1)
screen.add(Rect(0, 0, 32, 32, 0))
screen.add(label)
service.show()

for loop_pass in range(6):
    now_ms = ticks_ms()
    if service.check(now_ms):
        service.handle(now_ms)    # one strip per pass; the loop stays live
print(panel.writes)               # [(0, 8), (8, 8), (16, 8), (24, 8)]
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Screen(panel, background=0)` | The scene: items in paint order and the rectangle the next flush paints; `add`, `mark`, `remove`, `mark_all`, and `flush()` |
| `Rect`, `Box`, `Line`, `Ring`, `Text`, `Sprite` | The items: a filled rectangle, an outline, a line, a one-pixel circle, a string in the built-in font or a `Font`, and a bitmap with a transparent value |
| `ScreenService(screen, refresh_interval_ms=50, ticks=None)` | Runner-shaped pacer that advances a flush one bus transfer per tick |
| `ScreenService.show()` | Mark a flush due; the next due tick starts it |
| `ScreenService.check(now_ms)` / `handle(now_ms)` | The runner contract: due-test, then one-transfer advance |
| `ScreenService.next_deadline(now_ms)` | Lets `Runner.wait()` sleep until the next flush is due |

### Panels

| Symbol | Description |
|---|---|
| `chumicro_screens.gc9a01a.GC9A01A` | 240x240 round color TFT over SPI, both runtimes: bring-up plus one strip write per advance, `rows` rows of RGB565 at a time |
| `chumicro_screens.gc9a01a.color565(red, green, blue)` | Pack a color into the value the TFT's items draw in |
| `chumicro_screens.ssd1306.SSD1306` | 128x64 or 128x32 monochrome OLED over I2C, MicroPython: one page of eight rows per advance |
| `chumicro_screens.ssd1306.SSD1306.set_contrast(value)` | Drive current, 0 to 255, which is brightness on an emissive panel |
| `chumicro_screens.gc9a01a_displayio.make_display(display_bus)` | The round TFT as a displayio `BusDisplay` (CircuitPython; the firmware owns refresh) |
| `chumicro_screens.ssd1306_displayio.make_display(display_bus)` | The mono OLED as a displayio `BusDisplay` (CircuitPython) |
| `chumicro_screens.framebuf_strip.FramebufStrip` / `chumicro_screens.bitmap_strip.BitmapStrip` | The strip canvases a panel of your own hands a `Screen`: a `framebuf.FrameBuffer` a few rows tall on MicroPython, a `displayio.Bitmap` drawn with `bitmaptools` on CircuitPython |

### Fonts

| Symbol | Description |
|---|---|
| `chumicro_screens.fonts.Font(module)` | A font-to-py module (`font_to_py -x`) a `Text` item draws in, at the same pixels on both runtimes |
| `Font.width(string)` | Pixels a string spans, for centering; `height`, `baseline`, and `max_width` carry the module's metrics |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_screens.testing.FakeScreenPanel` | A panel whose strip records every primitive call with its band and whose `writes` lists every strip sent |
| `chumicro_screens.testing.FakePanel` | A flush-protocol fake for `ScreenService` alone, counting transfers and injecting a bus fault |

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for tick arithmetic, and on [`chumicro-compat`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) for the examples' pins and buses by GPIO number; the panels themselves take any bus and callable pins the app constructs.  Apps typically register the service with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), though a hand-written loop calling `check()` / `handle()` works the same.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

### Drivers ship after bench validation

Per-controller drivers are added as each passes validation on real boards.  The round GC9A01A TFT ships as `GC9A01A`, validated on a Pi Pico W under both runtimes: with a ring, a caption, and a count on the scene, an 8-row strip paints and sends in 2.6 ms mean and 2.9 ms worst under MicroPython and 2.8 ms and 3.7 ms under CircuitPython, a full paint in 78 ms and 84 ms across 30 advances with the loop live throughout, and a count's two strips in 5 ms and 6 ms.  The SSD1306 mono OLED ships as `SSD1306` on MicroPython, validated on the same board: a page paints and sends in 4.1 ms mean and 4.2 ms worst at 400 kHz, a frame in 8 pages and 32 ms, the count line in 2 pages and 8 ms, and `ssd1306_displayio.make_display` covers it on CircuitPython.  `fonts.Font` draws a font-to-py module on both panels.  Writing your own panel is `width`, `height`, a strip, and one method: `write_strip(top, count)` sending the strip's rows as one bounded transfer.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass on CPython, no hardware needed |
| [`gc9a01a_card.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_card.py) | A labeled color card to run first after wiring, one file for both runtimes; each bar names its color, so swapped channels and rotated mounts are visible at a glance |
| [`gc9a01a_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_counter.py) | A seconds counter on the round TFT, one file for both runtimes; each second marks one item and repaints two strips |
| [`gc9a01a_font_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/gc9a01a_font_counter.py) | The counter in a 20-pixel proportional font from a font-to-py module (`sans20.py` beside it), centered with `font.width()`, one file for both runtimes |
| [`circuitpython_gc9a01a_round.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_gc9a01a_round.py) | A color card on the round TFT via displayio, with a blinking notch proving live refresh (CircuitPython hardware) |
| [`micropython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_ssd1306_counter.py) | A bordered seconds counter on the mono OLED, one page per loop pass (MicroPython hardware) |
| [`micropython_ssd1306_font_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/micropython_ssd1306_font_counter.py) | The mono OLED counter in a 20-pixel proportional font from `sans20.py`, repainting the pages under the count each second (MicroPython hardware) |
| [`circuitpython_ssd1306_counter.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/circuitpython_ssd1306_counter.py) | A border and a growing bar on the mono OLED via displayio (CircuitPython hardware) |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/screens/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/screens/experimental/)**

## Find this library

- **PyPI:** [chumicro-screens](https://pypi.org/project/chumicro-screens/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_screens) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_screens)
- **Source:** [libraries/screens](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
