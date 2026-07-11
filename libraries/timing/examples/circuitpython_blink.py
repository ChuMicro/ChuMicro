"""Periodic LED blink — CircuitPython.

Toggles the onboard LED once per second using a non-blocking
``Rate`` timer (drift-free, phase-aligned cadence).  Prints a line
on each toggle so a serial console (or a sweep harness) can verify
the loop without watching the LED itself.

Setup:
1. Install ``chumicro_timing`` (``circup install chumicro_timing``
   or copy the package to ``lib/``).
2. No extra wiring — uses the built-in LED (``board.LED``).
   Works on most CircuitPython boards (Feather, QT Py, Metro, etc.).
3. Save this file as ``code.py`` on the board.

Example output::

    Running LED blink (1 Hz)...

      blink!
      blink!
      ...

Runs on CircuitPython.
"""

#: CircuitPython-only — uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_blink.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_timing import Rate, ticks_ms

# Set up the onboard LED as a digital output.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# Create a drift-free cadence that fires once per second.
beat = Rate(1000, ticks_ms())

print("Running LED blink (1 Hz)...\n")

while True:
    now = ticks_ms()

    # due() returns True at most once per period, staying phase-aligned.
    if beat.due(now):
        led.value = not led.value
        print("  blink!")
