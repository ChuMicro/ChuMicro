"""Count seconds in a 20-pixel proportional font on a monochrome SSD1306 OLED from MicroPython.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, VCC=3V3, GND=GND.
For a Pi Pico W use SDA=GP4, SCL=GP5 and make the numbers below
sda=4, scl=5.  The panel's default address is 0x3C, or 0x3D when the
module's address jumper is bridged.

``sans20.py`` beside this file is DejaVu Sans at 20 pixels, written
on the host by ``font_to_py -x DejaVuSans.ttf 20 sans20.py``, and the
deploy ships it with the example.  The caption and the count are
``Text`` items built with the ``Font``, centered with ``font.width()``;
each second the count gets its new string and position and is marked,
so the flush repaints the three pages it covers rather than all eight.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

import sans20
from chumicro_compat.wiring import i2c_bus
from chumicro_screens import Box, Screen, ScreenService, Text
from chumicro_screens.fonts import Font
from chumicro_screens.ssd1306 import SSD1306
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)
font = Font(sans20)

LIT = 1
caption = "seconds"
screen.add(Box(0, 0, 128, 64, LIT))
screen.add(Text((screen.width - font.width(caption)) // 2, 4, caption, LIT, font))
count = Text(0, 32, "0", LIT, font)
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
        count.x = (screen.width - font.width(count.string)) // 2
        screen.mark(count)
        service.show()
        print("frame", seconds, "shown")
    if service.check(now_ms):
        service.handle(now_ms)
