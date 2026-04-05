"""Periodic action using tick functions directly.

Shows the manual version of what ``Heartbeat`` does internally —
running an action every N milliseconds using ``ticks_ms`` and
``ticks_diff``.  This is the simplest tick-based timing loop and
a good starting point before reaching for ``Heartbeat``.

Example output::

    Periodic tick demo (every 1000 ms)...

      [  1000 ms] tick
      [  2001 ms] tick
      [  3001 ms] tick
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_diff, ticks_ms

INTERVAL_MS = 1000

last_fire = ticks_ms()

print(f"Periodic tick demo (every {INTERVAL_MS} ms)...\n")

_start = last_fire

while True:
    now = ticks_ms()

    if ticks_diff(now, last_fire) >= INTERVAL_MS:
        elapsed = ticks_diff(now, _start)
        print(f"  [{elapsed:5d} ms] tick")

        # Reset to "now".  This is simple but can drift slightly
        # because the sleep granularity adds a few ms each cycle.
        # Heartbeat avoids this by advancing by the period instead.
        last_fire = now

    # In a real project, the rest of your main loop goes here.
    time.sleep(0.01)
