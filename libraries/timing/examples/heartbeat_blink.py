"""Periodic blink — the embedded hello world.

Prints a message once per second using a non-blocking ``Rate`` timer.
``Rate`` is drift-free: it fires on a phase-aligned cadence rather than
re-anchoring to the moment you happened to poll.  On a real board,
replace the ``print`` with an LED toggle (``led.value = not led.value``).

Example output::

    Running periodic blink...

      beat!
      beat!
      beat!
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Rate, ticks_ms

# Create a drift-free cadence that fires once per second.  Rate needs
# the current time at construction so it can phase-align its schedule.
beat = Rate(1000, ticks_ms())

print("Running periodic blink...\n")

while True:
    # Capture the current time once per loop.  Passing the same now
    # value to every timing check means they all see the same moment,
    # with no drift between back-to-back calls.
    now = ticks_ms()

    # due() returns True at most once per period and advances the
    # schedule by whole periods.  It returns False on every other call.
    if beat.due(now):
        # On a real board: led.value = not led.value
        print("  beat!")

    # In a real project, the rest of your main loop goes here:
    # reading sensors, checking buttons, updating displays, etc.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.01)
