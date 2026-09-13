"""Count seconds on a GC9A01A round TFT: one file, both runtimes.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP10, DC=GP8, RST=GP9,
VCC=3V3, GND=GND, which leaves GP4 and GP5 free for an I2C panel on
the same board.  The panel's SCL/SDA silk is SPI clock and data, not
I2C.  For a LOLIN S2 Mini wire SCL=IO7, SDA=IO11, CS=IO12, DC=IO9,
RST=IO5 and make the numbers below controller 1, sck=7, mosi=11,
miso=3, and pins 12, 9, 5.

The ring and the caption are added once; each second the count item
gets its new string and is marked, so the flush repaints the two
strips under it rather than the panel, and the loop stays live
through every transfer.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import Ring, Screen, ScreenService, Text
from chumicro_screens.gc9a01a import GC9A01A, color565
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=16, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(10, value=1),
                digital_output(8, value=0),
                digital_output(9, value=1))
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=100)

WHITE = color565(255, 255, 255)
ACCENT = color565(255, 128, 0)
screen.add(Ring(120, 120, 118, ACCENT))
screen.add(Text(92, 100, "SECONDS", WHITE))
count = Text(116, 124, "0", WHITE)
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
