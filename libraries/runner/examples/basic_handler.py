"""Run three plain functions from one loop: two on timers, one on every pass.

The program prints a report once a second and a reminder every five seconds,
forever.  A third job has no period, so the runner calls it on every pass of
the loop.  It counts the passes, and the report shows how few there are:
``runner.wait()`` sleeps until the next timed job is due, so the loop goes
round once each time a timed job comes due, not thousands of times a second.
That is one pass a second here, plus one for each reminder.

A job with no period only runs when something else wakes the loop.  Give a
job that reads hardware, like a button, its own ``period_ms`` instead.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python basic_handler.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.

Example output::

    Running three jobs...
    1 s: the loop has gone round 2 times
    2 s: the loop has gone round 3 times
    3 s: the loop has gone round 4 times
    4 s: the loop has gone round 5 times
    five-second reminder
    5 s: the loop has gone round 7 times
    6 s: the loop has gone round 8 times
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner

passes = 0
seconds = 0


def count_pass(now_ms: int) -> None:
    """Count one pass of the loop.

    The runner passes every job ``now_ms``, the time of the current tick in
    milliseconds.  None of the jobs here need it.
    """
    global passes
    passes += 1


def report(now_ms: int) -> None:
    """Print how many times the loop has gone round so far."""
    global seconds
    seconds += 1
    print(f"{seconds} s: the loop has gone round {passes} times")


def remind(now_ms: int) -> None:
    """Print a reminder."""
    print("five-second reminder")


runner = Runner()
runner.add(handler=count_pass)                 # no period: runs on every pass
runner.add_periodic(report, period_ms=1000)    # once a second
runner.add_periodic(remind, period_ms=5000)    # every five seconds

print("Running three jobs...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next timed job is due
