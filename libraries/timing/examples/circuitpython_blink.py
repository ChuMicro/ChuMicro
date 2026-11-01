"""Blink the onboard LED once a second without pausing the loop, on CircuitPython.

The onboard LED stays on for a second, then off for a second, and the serial
console prints each change.  ``Rate`` says when a second has passed, so the
loop never sleeps and anything you add to it keeps running.  This is
Arduino's BlinkWithoutDelay, with ``ticks_ms()`` in place of ``millis()``.

Wiring: none.  ``board.LED`` is the onboard LED on a Pi Pico W and on ESP32-S2
boards such as the Lolin S2 Mini.

Example output::

    Blinking the onboard LED once a second.

      LED on
      LED off
      LED on
      ...

Setup:
1. Install the library: ``circup install chumicro_timing``.
2. Save this file as ``code.py`` on the CIRCUITPY drive.

Runs on CircuitPython.
"""

# ChuMicro's example tools read this line: this file needs CircuitPython.
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# A timer that comes due every 1000 ms, counting from now.
every_second = Rate(1000, ticks_ms())

print("Blinking the onboard LED once a second.\n")

while True:
    now = ticks_ms()

    # due() is True once each time a second has passed, and False otherwise.
    if every_second.due(now):
        led.value = not led.value
        print("  LED on" if led.value else "  LED off")

    # Nothing above waits, so code you add here runs on every pass.
