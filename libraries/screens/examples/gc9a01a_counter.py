"""Count seconds on a GC9A01A round TFT while the loop stays live: one file, both runtimes.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP5, DC=GP8, RST=GP9,
VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and data,
not I2C.  For a LOLIN S2 Mini wire SCL=IO7, SDA=IO11, CS=IO12,
DC=IO9, RST=IO5 and make the numbers below controller 1, sck=7,
mosi=11, miso=3, and pins 12, 9, 5.

The ring and the caption are drawn once.  Each second clears and
redraws the count alone, and the flush sends only the strips that
band covers, windowed to its columns: two 6-row strips on MicroPython
and three 3-row strips on CircuitPython, against forty and eighty for
the first frame.  Each strip crosses the bus on its own loop pass, so
the loop never blocks longer than a few milliseconds on either
runtime.  The frame is one byte per pixel on both, expanded through
the palette per strip, and on CircuitPython it streams straight over
the bus, bypassing displayio.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01AIndexed
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

spi = spi_bus(0, sck=6, mosi=7, miso=4, baudrate=40_000_000)
panel = GC9A01AIndexed(spi,
                       digital_output(5, value=1),
                       digital_output(8, value=0),
                       digital_output(9, value=1))
screen = ScreenService(panel, refresh_interval_ms=100)

BLACK, WHITE, ACCENT = 0, 1, 2
panel.set_color(WHITE, 255, 255, 255)
panel.set_color(ACCENT, 255, 128, 0)
frame = panel.frame
frame.fill(BLACK)
frame.ellipse(120, 120, 118, 118, ACCENT)
frame.text("SECONDS", 92, 100, WHITE)

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        frame.fill_rect(92, 124, 56, 8, BLACK)
        frame.text(str(seconds), 116, 124, WHITE)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
