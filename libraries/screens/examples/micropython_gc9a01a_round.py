"""Count seconds on a GC9A01A round TFT while the loop stays live.

Wiring for a LOLIN S2 Mini: SCL=IO7, SDA=IO11, CS=IO12, DC=IO9,
RST=IO5, VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and
data, not I2C.  Any MicroPython board works with its own SPI-capable
GPIO numbers substituted.

The redraw happens once a second; the ~115 KB frame then crosses the
bus one 10-row strip per loop pass, so the loop never blocks longer
than a few milliseconds.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

from chumicro_compat.wiring import digital_output, spi_bus
from chumicro_screens import ScreenService
from chumicro_screens.gc9a01a import GC9A01A, color565
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

spi = spi_bus(1, sck=7, mosi=11, miso=3, baudrate=40_000_000)
panel = GC9A01A(spi,
                digital_output(12, value=1),
                digital_output(9, value=0),
                digital_output(5, value=1))
screen = ScreenService(panel, refresh_interval_ms=100)

white = color565(255, 255, 255)
accent = color565(255, 128, 0)
frame = panel.frame

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        frame.fill(0)
        frame.ellipse(120, 120, 118, 118, accent)
        frame.text("SECONDS", 92, 100, white)
        frame.text(str(seconds), 116, 124, white)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
