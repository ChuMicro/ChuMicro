"""Blink the onboard LED once a second without pausing the loop, on MicroPython.

The onboard LED stays on for a second, then off for a second, and the serial
console prints each change.  ``Rate`` says when a second has passed, so the
loop never sleeps and anything you add to it keeps running.  This is
Arduino's BlinkWithoutDelay, with ``ticks_ms()`` in place of ``millis()``.

Wiring: none.  ``LED_PIN`` below names the onboard LED: ``"LED"`` on a Pi
Pico W.  On an ESP32 board, set it to the LED's GPIO number, which is 15 on a
Lolin S2 Mini and 2 on most ESP32 dev boards.

Example output::

    Blinking the onboard LED once a second.

      LED on
      LED off
      LED on
      ...

Setup:
1. Install the library:
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing``.
2. Copy this file to the board as ``main.py``.

Runs on MicroPython.
"""

# ChuMicro's example tools read this line: this file needs MicroPython.
__chumicro_runtimes__ = ("micropython",)

from chumicro_timing import Rate, ticks_ms
from machine import Pin

LED_PIN = "LED"     # Pi Pico W.  15 on a Lolin S2 Mini, 2 on most ESP32 dev boards.

led = Pin(LED_PIN, Pin.OUT)

# A timer that comes due every 1000 ms, counting from now.
every_second = Rate(1000, ticks_ms())

print("Blinking the onboard LED once a second.\n")

while True:
    now = ticks_ms()

    # due() is True once each time a second has passed, and False otherwise.
    if every_second.due(now):
        led.value(not led.value())
        print("  LED on" if led.value() else "  LED off")

    # Nothing above waits, so code you add here runs on every pass.
