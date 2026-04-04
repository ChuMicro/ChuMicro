"""Multiple heartbeats at different rates.

Demonstrates the shared-timestamp pattern: capture ``ticks_ms()`` once
per loop iteration and pass the same value to every heartbeat.  This
ensures all components see the same moment in time — no drift between
calls.

On a real board, each heartbeat could drive a different LED or sensor
polling rate.

Example output::

    Running multiple heartbeats...

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

from chumicro_timing import Heartbeat, ticks_ms

# Create heartbeats at different rates.  Each one tracks its own
# schedule independently.
fast = Heartbeat(period_ms=200)
medium = Heartbeat(period_ms=1000)
slow = Heartbeat(period_ms=5000)

print("Running multiple heartbeats...\n")

while True:
    # Capture time once and share it with all heartbeats.
    # This is the "shared-timestamp pattern" — all components
    # see the same moment, so two heartbeats that happen to
    # fire on the same tick will both see the same now value.
    now = ticks_ms()

    if fast.poll(now):
        print("  fast (200 ms)")
    if medium.poll(now):
        print("  medium (1 s)")
    if slow.poll(now):
        print("  slow (5 s)")

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.01)
