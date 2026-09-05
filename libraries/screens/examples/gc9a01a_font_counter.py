"""Count seconds in a 20-pixel proportional font on a GC9A01A round TFT: one file, both runtimes.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP5, DC=GP8, RST=GP9,
VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and data,
not I2C.  For a LOLIN S2 Mini wire SCL=IO7, SDA=IO11, CS=IO12,
DC=IO9, RST=IO5 and make the numbers below controller 1, sck=7,
mosi=11, miso=3, and pins 12, 9, 5.

``sans20.py`` beside this file is DejaVu Sans at 20 pixels, written
on the host by ``font_to_py -x DejaVuSans.ttf 20 sans20.py``, and the
deploy ships it with the example.  ``Font`` draws it through each
runtime's own C blit, so the caption and the count land on the same
pixels under MicroPython and CircuitPython, and ``font.width()``
centers each string.  The small tag at the bottom is in the canvas's
built-in font, the one line whose face differs between the runtimes.
The ring, the caption, and the tag are drawn once; each second clears
and redraws the count alone, so the flush sends the few strips that
band covers rather than the frame.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

import sans20
from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.fonts import Font
from chumicro_screens.gc9a01a import GC9A01AIndexed
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01AIndexed(spi,
                       digital_output(5, value=1),
                       digital_output(8, value=0),
                       digital_output(9, value=1))
screen = ScreenService(panel, refresh_interval_ms=100)
font = Font(sans20)

BLACK, WHITE, ACCENT = 0, 1, 2
panel.set_color(WHITE, 255, 255, 255)
panel.set_color(ACCENT, 255, 128, 0)
frame = panel.frame
caption = "seconds"
frame.fill(BLACK)
frame.ellipse(120, 120, 118, 118, ACCENT)
font.text(frame, caption, (panel.width - font.width(caption)) // 2, 84, WHITE)
frame.text("chumicro screens", 56, 200, WHITE)

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        count = str(seconds)
        frame.fill_rect(60, 116, 120, font.height, BLACK)
        font.text(frame, count, (panel.width - font.width(count)) // 2, 116, ACCENT)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
