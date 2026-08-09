"""Multiple Rate timers at different rates.

Demonstrates the shared-timestamp pattern: capture ``ticks_ms()`` once
per loop iteration and pass the same value to every timer.  This
ensures all components see the same moment in time, with no drift between
calls.

On a real board, each timer could drive a different LED or sensor
polling rate.

Example output::

    Running multiple timers...

      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      medium (1 s)
      fast (200 ms)
      ...
      slow (5 s)
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Rate, ticks_ms

# Create Rate timers at different rates.  Each one tracks its own
# drift-free schedule independently.  Share one timestamp so every
# timer phase-aligns to the same starting moment.
now = ticks_ms()
fast = Rate(200, now)
medium = Rate(1000, now)
slow = Rate(5000, now)

print("Running multiple timers...\n")

while True:
    # Capture time once and share it with all timers.
    # This is the "shared-timestamp pattern": all components
    # see the same moment, so two timers that happen to
    # fire on the same tick will both see the same now value.
    now = ticks_ms()

    if fast.due(now):
        print("  fast (200 ms)")
    if medium.due(now):
        print("  medium (1 s)")
    if slow.due(now):
        print("  slow (5 s)")

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.01)
