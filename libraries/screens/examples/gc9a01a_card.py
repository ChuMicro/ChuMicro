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
two runtimes draw their own built-in fonts here, so the labels differ
in size, not in place; ``gc9a01a_font_counter.py`` draws a converted
font that lands on the same pixels on both.

Nothing here holds a frame: the scene is a handful of items, and the
flush paints the panel eight rows at a time from a 3.8 KB strip, one
strip per loop pass.

Example output::

    card shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import Rect, Ring, Screen, ScreenService, Text
from chumicro_screens.gc9a01a import GC9A01A, color565
from chumicro_timing import ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(5, value=1),
                digital_output(8, value=0),
                digital_output(9, value=1))
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)

BLACK = color565(0, 0, 0)
WHITE = color565(255, 255, 255)
RED = color565(255, 0, 0)
GREEN = color565(0, 255, 0)
BLUE = color565(0, 0, 255)

screen.add(Ring(120, 120, 118, WHITE))
screen.add(Text(56, 24, "CHUMICRO SCREENS", WHITE))
screen.add(Rect(40, 48, 160, 40, RED))
screen.add(Text(108, 64, "RED", WHITE))
screen.add(Rect(40, 100, 160, 40, GREEN))
screen.add(Text(100, 116, "GREEN", BLACK))
screen.add(Rect(40, 152, 160, 40, BLUE))
screen.add(Text(104, 168, "BLUE", WHITE))
screen.add(Text(80, 208, "WIRING OK?", WHITE))
service.show()
print("card shown")

while True:
    now_ms = ticks_ms()
    if service.check(now_ms):
        service.handle(now_ms)
