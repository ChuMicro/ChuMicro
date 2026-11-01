"""Run code once a second by hand, the way Arduino's BlinkWithoutDelay does.

The console prints ``tick`` about once a second, with how far behind the
ideal schedule (exactly 1000, 2000, 3000 ms) that tick landed.  Watch that
number grow.  Each wait starts from the moment the loop noticed the last
tick, so a check that arrives a few milliseconds late pushes every later tick
back by the same amount, and the delays pile up.

If you know Arduino, this is BlinkWithoutDelay line for line: ``ticks_ms()``
is ``millis()``, ``last_tick_ms`` is ``previousMillis``, and
``ticks_diff(now, last_tick_ms)`` is ``currentMillis - previousMillis``.  The
subtraction goes through ``ticks_diff`` because the millisecond counter rolls
over to zero every few days, and plain subtraction gives a wrong answer
across that rollover.

``phase_locked_tick.py`` stops the pile-up with a one-line change, and
``Rate`` makes that change for you.

Example output::

    Ticking every 1000 ms, each wait starting from the last tick.

      [ 1007 ms] tick, 7 ms behind schedule
      [ 2012 ms] tick, 12 ms behind schedule
      [ 3021 ms] tick, 21 ms behind schedule
      [ 4030 ms] tick, 30 ms behind schedule
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_diff, ticks_ms

INTERVAL_MS = 1000

started_ms = ticks_ms()
last_tick_ms = started_ms
tick_count = 0

print(f"Ticking every {INTERVAL_MS} ms, each wait starting from the last tick.\n")

while True:
    now = ticks_ms()

    if ticks_diff(now, last_tick_ms) >= INTERVAL_MS:
        tick_count += 1
        elapsed_ms = ticks_diff(now, started_ms)
        behind_ms = elapsed_ms - tick_count * INTERVAL_MS
        print(f"  [{elapsed_ms:5d} ms] tick, {behind_ms} ms behind schedule")

        # The next wait starts from now, the moment this tick was noticed.
        # Whatever lateness this tick had stays in the schedule for good.
        last_tick_ms = now

    # Stand-in for the rest of a real program, which takes time on every
    # pass.  That time is what makes a check land late.
    time.sleep(0.01)
