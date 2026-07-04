"""Phase-locked periodic action — drift-free deadline carrier.

Shows the manual deadline-carrier pattern: each fire schedules the next
one by adding the period to the *last deadline*, not to *now*.  This
keeps the schedule phase-locked even when the loop runs late.

This is exactly what ``Rate`` does internally — ``Rate`` is the built-in
drift-free cadence, and reaching for it is usually simpler than carrying
the deadline by hand.  Contrast with ``periodic_tick.py``, which
re-anchors the next deadline to *now* and so drifts forward by the loop's
late-arrival cost on every cycle.  When the period must mean what it says
(telemetry "10 messages per minute", a sensor read every 200 ms), stay
phase-locked — reach for ``Rate`` or spell it out with this pattern.

Example output::

    Phase-locked tick demo (every 1000 ms)...

      [ 1000 ms] tick (lateness  0 ms)
      [ 2000 ms] tick (lateness  0 ms)
      [ 3000 ms] tick (lateness  0 ms)
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

PERIOD_MS = 1000

start = ticks_ms()
next_deadline = ticks_add(start, PERIOD_MS)

print(f"Phase-locked tick demo (every {PERIOD_MS} ms)...\n")

while True:
    now = ticks_ms()

    if ticks_diff(now, next_deadline) >= 0:
        elapsed = ticks_diff(now, start)
        lateness = ticks_diff(now, next_deadline)
        print(f"  [{elapsed:5d} ms] tick (lateness {lateness:>2d} ms)")

        # Anchor the next deadline to the *previous deadline*, not to
        # now.  Even if the loop arrived late and now > next_deadline by
        # a few ms, the schedule stays on the original cadence — the
        # next tick comes PERIOD_MS after the deadline we just hit.
        next_deadline = ticks_add(next_deadline, PERIOD_MS)

    # In a real project, the rest of your main loop goes here.
    time.sleep(0.01)
