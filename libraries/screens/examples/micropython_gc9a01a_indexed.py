"""Count seconds on a GC9A01A round TFT from a 256 KB-class board.

Wiring for a Pi Pico W: SCK=GP6, MOSI=GP7, CS=GP5, DC=GP8, RST=GP9,
VCC=3V3, GND=GND.  The panel's SCL/SDA silk is SPI clock and data,
not I2C.  Any MicroPython board works with its own SPI-capable GPIO
numbers substituted.

GC9A01AIndexed holds the frame at one byte per pixel plus a
256-entry palette, about half the RAM of the full-color driver, so a
Pico W heap fits it.  Drawing uses palette indexes as colors; each
loop pass expands and sends one 6-row strip, so the loop never
blocks longer than a few milliseconds.

Example output::

    frame 1 shown
    frame 2 shown
"""
__chumicro_runtimes__ = ("micropython",)

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

seconds = 0
next_draw_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_draw_ms) >= 0:
        next_draw_ms = ticks_add(now_ms, 1000)
        seconds += 1
        frame.fill(BLACK)
        frame.ellipse(120, 120, 118, 118, ACCENT)
        frame.text("SECONDS", 92, 100, WHITE)
        frame.text(str(seconds), 116, 124, WHITE)
        screen.show()
        print("frame", seconds, "shown")
    if screen.check(now_ms):
        screen.handle(now_ms)
