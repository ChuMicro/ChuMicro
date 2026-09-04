"""Count seconds on a monochrome SSD1306 OLED via displayio.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, VCC=3V3, GND=GND.
For a Pi Pico W use SDA=GP4, SCL=GP5.  The panel's default address is
0x3C, or 0x3D when the module's address jumper is bridged.  The OLED
is emissive and makes its own drive voltage on an internal charge
pump, so it runs from 3V3.

displayio repaints changed regions in the background at C speed, so
there is no ScreenService here: mutate the bitmap and the panel
follows.  A one-pixel border proves the panel's full extent is
addressed, and a bar that grows a column a second proves live
refresh; together they catch an off-by-one geometry or a stalled
update in one look.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("circuitpython",)

import displayio
import i2cdisplaybus
from chumicro_compat.wiring import i2c_bus
from chumicro_screens.ssd1306_displayio import make_display
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

displayio.release_displays()
i2c = i2c_bus(0, scl=35, sda=33, frequency=400_000)
display = make_display(i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C))

DARK, LIT = 0, 1
palette = displayio.Palette(2)
palette[DARK] = 0x000000
palette[LIT] = 0xFFFFFF

canvas = displayio.Bitmap(display.width, display.height, 2)
canvas.fill(DARK)
for column in range(display.width):
    canvas[column, 0] = LIT
    canvas[column, display.height - 1] = LIT
for row in range(display.height):
    canvas[0, row] = LIT
    canvas[display.width - 1, row] = LIT

group = displayio.Group()
group.append(displayio.TileGrid(canvas, pixel_shader=palette))
display.root_group = group

BAR_TOP = 24
BAR_BOTTOM = 40
seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        column = 4 + seconds % (display.width - 8)
        if column == 4:
            for blank in range(4, display.width - 4):
                for row in range(BAR_TOP, BAR_BOTTOM):
                    canvas[blank, row] = DARK
        for row in range(BAR_TOP, BAR_BOTTOM):
            canvas[column, row] = LIT
        print("frame", seconds, "shown")
