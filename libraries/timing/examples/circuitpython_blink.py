"""Heartbeat LED blink — CircuitPython.

Toggles the onboard LED once per second using a non-blocking
``Heartbeat`` timer.

Setup:
1. Install ``chumicro_timing`` (``circup install chumicro-timing``
   or copy the package to ``lib/``).
2. No extra wiring — uses the built-in LED (``board.LED``).
   Works on most CircuitPython boards (Feather, QT Py, Metro, etc.).
3. Save this file as ``code.py`` on the board.

Runs on CircuitPython.
"""

#: CircuitPython-only — uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_blink.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

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
