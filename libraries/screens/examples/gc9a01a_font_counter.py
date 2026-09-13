"""Count seconds in a 20-pixel proportional font on a GC9A01A round TFT: one file, both runtimes.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP5, DC=GP8, RST=GP9,
VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and data,
not I2C.  For a LOLIN S2 Mini wire SCL=IO7, SDA=IO11, CS=IO12,
DC=IO9, RST=IO5 and make the numbers below controller 1, sck=7,
mosi=11, miso=3, and pins 12, 9, 5.

``sans20.py`` beside this file is DejaVu Sans at 20 pixels, written
on the host by ``font_to_py -x DejaVuSans.ttf 20 sans20.py``, and the
deploy ships it with the example.  A ``Text`` item built with the
``Font`` lands on the same pixels under MicroPython and CircuitPython,
and ``font.width()`` centers each string.  The small tag at the bottom
is in the built-in font, the one line whose face differs between the
runtimes.  Each second the count gets its new string and position and
is marked, so the flush repaints the strips under it alone.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

import sans20
from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import Ring, Screen, ScreenService, Text
from chumicro_screens.fonts import Font
from chumicro_screens.gc9a01a import GC9A01A, color565
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(5, value=1),
                digital_output(8, value=0),
                digital_output(9, value=1))
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)
font = Font(sans20)

WHITE = color565(255, 255, 255)
ACCENT = color565(255, 128, 0)
caption = "seconds"
screen.add(Ring(120, 120, 118, ACCENT))
screen.add(Text((screen.width - font.width(caption)) // 2, 84, caption, WHITE, font))
count = Text(0, 116, "0", WHITE, font)
screen.add(count)
screen.add(Text(84, 200, "font-to-py", ACCENT))
service.show()

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        count.string = str(seconds)
        count.x = (screen.width - font.width(count.string)) // 2
        screen.mark(count)
        service.show()
        print("frame", seconds, "shown")
    if service.check(now_ms):
        service.handle(now_ms)
