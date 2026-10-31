"""Run three jobs at three different speeds from one loop.

The console prints ``fast`` five times a second, ``medium`` once a second,
and ``slow`` every five seconds, all from one loop that never pauses.  Each
``Rate`` keeps its own schedule.  On a board the three jobs might blink an
LED, read a sensor, and send a report.

The loop reads the clock once at the top of each pass and hands that one
reading to every timer.  Timers that come due at the same moment then fire on
the same pass, instead of one of them slipping to the next.

Example output::

    Running three timers: every 200 ms, every second, every 5 seconds.

      fast
      fast
      fast
      fast
      fast
      medium
      fast
      ...
      slow
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_timing import Rate, ticks_ms

# Start all three timers from the same reading so their schedules line up.
now = ticks_ms()
fast = Rate(200, now)
medium = Rate(1000, now)
slow = Rate(5000, now)

print("Running three timers: every 200 ms, every second, every 5 seconds.\n")

while True:
    # One clock reading per pass, shared by every timer below.
    now = ticks_ms()

    if fast.due(now):
        print("  fast")
    if medium.due(now):
        print("  medium")
    if slow.due(now):
        print("  slow")

    # Nothing above waits, so code you add here runs on every pass.
