"""Show a color card on a GC9A01A round TFT via displayio.

Wiring for a LOLIN S2 Mini: SCL=IO7, SDA=IO11, CS=IO12, DC=IO9,
RST=IO5, VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and
data, not I2C.  For a Pi Pico W wire SCK=GP6, MOSI=GP7, CS=GP5,
DC=GP8, RST=GP9 and change the GPIO numbers below to match.

displayio repaints changed regions in the background at C speed, so
there is no ScreenService here: mutate a palette and the panel
follows.  The card shows a red bar on top, green in the middle, blue
at the bottom, and a white notch at top center that blinks once a
second; that order plus the blink validates colors, orientation, and
live refresh in one look.

Example output::

    step 1
    step 2
"""
__chumicro_runtimes__ = ("circuitpython",)

import displayio
import fourwire
from chumicro_compat.wiring import gpio_pin, spi_bus
from chumicro_screens.gc9a01a_displayio import make_display
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

displayio.release_displays()
spi = spi_bus(1, sck=7, mosi=11)
display = make_display(fourwire.FourWire(
    spi, command=gpio_pin(9), chip_select=gpio_pin(12), reset=gpio_pin(5),
    baudrate=40_000_000))

bar_palette = displayio.Palette(3)
bar_palette[0] = 0xFF0000
bar_palette[1] = 0x00FF00
bar_palette[2] = 0x0000FF
bars = displayio.Bitmap(3, 3, 3)
for column in range(3):
    for row in range(3):
        bars[column, row] = row
bar_group = displayio.Group(scale=80)
bar_group.append(displayio.TileGrid(bars, pixel_shader=bar_palette))

notch_palette = displayio.Palette(1)
notch_palette[0] = 0xFFFFFF
notch = displayio.Bitmap(1, 1, 1)
notch_group = displayio.Group(scale=16)
notch_group.append(displayio.TileGrid(notch, pixel_shader=notch_palette,
                                      x=7, y=1))

root = displayio.Group()
root.append(bar_group)
root.append(notch_group)
display.root_group = root

step = 0
next_step_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_step_ms) >= 0:
        next_step_ms = ticks_add(now_ms, 1000)
        step += 1
        notch_palette[0] = 0xFFFFFF if step % 2 else 0x000000
        print("step", step)
