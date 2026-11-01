"""Run code once a second by hand, without letting the schedule slip.

The console prints ``tick`` once a second, with how far behind the ideal
schedule (exactly 1000, 2000, 3000 ms) that tick landed.  Unlike
``periodic_tick.py``, the number never grows past the time one pass of the
loop takes.  Each tick is scheduled one second after the previous tick was
*due*, not one second after the loop noticed it, so a late check delays that
one tick and nothing after it.

That one-line difference is what ``Rate`` does inside.  In your own code use
``Rate``; this file is here to show how it works.

Example output::

    Ticking every 1000 ms, each tick scheduled from the last one's due time.

      [ 1000 ms] tick, 0 ms behind schedule
      [ 2009 ms] tick, 9 ms behind schedule
      [ 3005 ms] tick, 5 ms behind schedule
      [ 4009 ms] tick, 9 ms behind schedule
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

PERIOD_MS = 1000

started_ms = ticks_ms()
next_due_ms = ticks_add(started_ms, PERIOD_MS)
tick_count = 0

print(f"Ticking every {PERIOD_MS} ms, each tick scheduled from the last one's due time.\n")

while True:
    now = ticks_ms()

    if ticks_diff(now, next_due_ms) >= 0:
        tick_count += 1
        elapsed_ms = ticks_diff(now, started_ms)
        behind_ms = elapsed_ms - tick_count * PERIOD_MS
        print(f"  [{elapsed_ms:5d} ms] tick, {behind_ms} ms behind schedule")

        # The next tick is due one period after this one was due, however
        # late the loop got here.  ticks_add, not +, keeps the sum correct
        # when the millisecond counter rolls over.
        next_due_ms = ticks_add(next_due_ms, PERIOD_MS)

    # Stand-in for the rest of a real program, which takes time on every
    # pass.  That time is what makes a check land late.
    time.sleep(0.01)
