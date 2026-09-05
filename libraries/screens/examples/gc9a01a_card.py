"""Draw a labeled color card on a GC9A01A round TFT: one file, both runtimes.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP5, DC=GP8, RST=GP9,
VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and data,
not I2C.  For a LOLIN S2 Mini wire SCL=IO7, SDA=IO11, CS=IO12,
DC=IO9, RST=IO5 and make the numbers below controller 1, sck=7,
mosi=11, miso=3, and pins 12, 9, 5.  The same numbers serve
MicroPython and CircuitPython, and so does every line after them.

Run this first after wiring a panel.  Each bar carries its own name,
which catches the mistakes a solid fill cannot: swapped color
channels render "RED" on a blue bar, and a rotated or mirrored mount
moves the bars off their named positions.  When every label sits on
its own color, the wiring and the byte order are both right.  The
two runtimes draw their own built-in fonts, so the labels differ in
size, not in place.

Example output::

    card shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01AIndexed
from chumicro_timing import ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01AIndexed(spi,
                       digital_output(5, value=1),
                       digital_output(8, value=0),
                       digital_output(9, value=1))
screen = ScreenService(panel, refresh_interval_ms=100)

BLACK, WHITE, RED, GREEN, BLUE = range(5)
panel.set_color(WHITE, 255, 255, 255)
panel.set_color(RED, 255, 0, 0)
panel.set_color(GREEN, 0, 255, 0)
panel.set_color(BLUE, 0, 0, 255)

frame = panel.frame
frame.fill(BLACK)
frame.ellipse(120, 120, 118, 118, WHITE)
frame.text("CHUMICRO SCREENS", 56, 24, WHITE)
frame.fill_rect(40, 48, 160, 40, RED)
frame.text("RED", 108, 64, WHITE)
frame.fill_rect(40, 100, 160, 40, GREEN)
frame.text("GREEN", 100, 116, BLACK)
frame.fill_rect(40, 152, 160, 40, BLUE)
frame.text("BLUE", 104, 168, WHITE)
frame.text("WIRING OK?", 80, 208, WHITE)
screen.show()
print("card shown")

while True:
    now_ms = ticks_ms()
    if screen.check(now_ms):
        screen.handle(now_ms)
