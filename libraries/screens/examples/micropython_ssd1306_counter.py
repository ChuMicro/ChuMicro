"""Count seconds on a monochrome SSD1306 OLED from MicroPython.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, VCC=3V3, GND=GND.
For a Pi Pico W use SDA=GP4, SCL=GP5.  The panel's default address is
0x3C, or 0x3D when the module's address jumper is bridged.  Unlike a
character LCD's backpack, the OLED runs from 3V3: it is emissive and
makes its own drive voltage on an internal charge pump.

The frame is 1024 bytes and crosses the bus one page at a time, so no
single tick blocks on the transfer.  A border, a caption, and a
counter together prove addressing, text placement, and live refresh in
one look.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

from chumicro_compat.wiring import i2c_bus
from chumicro_screens import ScreenService
from chumicro_screens.ssd1306 import SSD1306
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

bus = i2c_bus(0, scl=35, sda=33, frequency=400_000)
panel = SSD1306(bus)
screen = ScreenService(panel, refresh_interval_ms=100)

DARK, LIT = 0, 1
frame = panel.frame

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        frame.fill(DARK)
        frame.rect(0, 0, 128, 64, LIT)
        frame.text("chumicro", 4, 8, LIT)
        frame.text("SECONDS", 4, 28, LIT)
        frame.text(str(seconds), 4, 44, LIT)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
