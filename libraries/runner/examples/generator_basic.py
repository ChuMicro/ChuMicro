"""Blink a heartbeat pattern with a generator task, written like a sleep blink.

The program prints a double blink every two seconds (on, off, on, then a
long off), forever.  Once a second a separate timed job prints that it is
still running on time.

``heartbeat_pattern`` reads top to bottom like a ``time.sleep()`` blink.  It
is a generator task: each ``yield from pause(...)`` hands the loop back to
the runner, which runs the other job and resumes the pattern on the next
line when the pause is over.  A ``time.sleep()`` in its place would stop the
other job until the sleep ended.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python generator_basic.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.

Example output::

    Blinking a heartbeat pattern...
    LED on
    LED off
    LED on
    LED off
    1 s: the other job is on time
    2 s: the other job is on time
    LED on
    LED off
    LED on
    LED off
    3 s: the other job is on time
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms


def pause(duration_ms: int):
    """Pause the generator task that calls this for ``duration_ms`` milliseconds.

    Call it as ``yield from pause(200)``, the generator-task version of
    ``time.sleep(0.2)``.  ``sleep_until`` takes an absolute time, so this adds
    the duration to the current tick.
    """
    yield from sleep_until(ticks_add(ticks_ms(), duration_ms))


def heartbeat_pattern():
    """Print a double blink forever: on 200 ms, off 200 ms, on 200 ms, off 1400 ms."""
    while True:
        print("LED on")
        yield from pause(200)
        print("LED off")
        yield from pause(200)
        print("LED on")
        yield from pause(200)
        print("LED off")
        yield from pause(1400)


seconds = 0


def count_seconds(now_ms: int) -> None:
    """Print the seconds since startup.

    The runner passes every job ``now_ms``, the time of the current tick in
    milliseconds.  This job counts its own seconds instead.
    """
    global seconds
    seconds += 1
    print(f"{seconds} s: the other job is on time")


print("Blinking a heartbeat pattern...")

runner = Runner()
runner.add_generator(heartbeat_pattern())             # runs up to its first pause right away
runner.add_periodic(count_seconds, period_ms=1000)    # once a second

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job or pause is due
