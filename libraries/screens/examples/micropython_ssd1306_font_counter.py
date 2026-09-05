"""Count seconds in a 20-pixel proportional font on a monochrome SSD1306 OLED from MicroPython.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, VCC=3V3, GND=GND.
For a Pi Pico W use SDA=GP4, SCL=GP5.  The panel's default address is
0x3C, or 0x3D when the module's address jumper is bridged.

``sans20.py`` beside this file is DejaVu Sans at 20 pixels, written
on the host by ``font_to_py -x DejaVuSans.ttf 20 sans20.py``, and the
deploy ships it with the example.  ``Font`` blits each glyph through
a palette in the frame's own 1-bit format, and ``font.width()``
centers each string.  The border and the caption are drawn once; each
second clears and redraws the count line, and the flush sends the
three pages that line covers rather than all eight.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

import sans20
from chumicro_compat.wiring import i2c_bus
from chumicro_screens import ScreenService
from chumicro_screens.fonts import Font
from chumicro_screens.ssd1306 import SSD1306
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)
screen = ScreenService(panel, refresh_interval_ms=100)
font = Font(sans20)

DARK, LIT = 0, 1
frame = panel.frame
caption = "seconds"
frame.fill(DARK)
frame.rect(0, 0, 128, 64, LIT)
font.text(frame, caption, (panel.width - font.width(caption)) // 2, 4, LIT)

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        count = str(seconds)
        frame.fill_rect(2, 32, 124, font.height, DARK)
        font.text(frame, count, (panel.width - font.width(count)) // 2, 32, LIT)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
