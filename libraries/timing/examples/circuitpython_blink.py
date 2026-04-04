# requires: hardware
"""Heartbeat LED blink — CircuitPython.

Toggles the onboard LED once per second using a non-blocking
``Heartbeat`` timer.  Drop this file onto your board as ``code.py``.

Wiring: none — uses the built-in LED (``board.LED``).  Works on
most CircuitPython boards (Feather, QT Py, Metro, etc.).

Runs on CircuitPython.
"""

import board
import digitalio
from chumicro_timing import Heartbeat, ticks_ms

# Set up the onboard LED as a digital output.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# Create a heartbeat that fires once per second.
heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()

    # poll() returns True once per period, then resets.
    if heartbeat.poll(now):
        led.value = not led.value

