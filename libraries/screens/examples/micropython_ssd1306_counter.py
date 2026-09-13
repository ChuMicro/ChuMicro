"""Count seconds on a monochrome SSD1306 OLED from MicroPython.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, VCC=3V3, GND=GND.
For a Pi Pico W use SDA=GP4, SCL=GP5 and make the numbers below
sda=4, scl=5.  The panel's default address is 0x3C, or 0x3D when the
module's address jumper is bridged.  Unlike a character LCD's
backpack, the OLED runs from 3V3: it is emissive and makes its own
drive voltage on an internal charge pump.

The scene is a border and three lines of text; the flush paints the
panel one 128-byte page at a time, so no tick blocks on the bus, and
each second's count repaints only the two pages under it.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

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
screen.add(Text(4, 28, "SECONDS", LIT))
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
        print("frame", seconds, "shown")
    if service.check(now_ms):
        service.handle(now_ms)
