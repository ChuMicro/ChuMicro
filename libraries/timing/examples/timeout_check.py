"""Timeout check using tick functions directly.

Shows how to use ``ticks_ms`` / ``ticks_diff`` / ``ticks_add`` for
deadline enforcement, the kind of one-shot timing logic that doesn't
fit the periodic ``Rate`` pattern.

A ``wait_for_sensor()`` helper polls until a sensor is ready or a
deadline expires.  On a real board, ``poll_sensor()`` would be a fast
non-blocking check (GPIO pin, status register, etc.).

Example output::

    Running timeout checks...

      Waiting for sensor (500 ms deadline)...
      [105 ms] not ready...
      [210 ms] not ready...
      [316 ms] not ready...
      [420 ms] sensor ready after 420 ms

      Waiting for sensor (500 ms deadline)...
      [104 ms] not ready...
      [209 ms] not ready...
      [315 ms] not ready...
      [421 ms] not ready...
      TIMEOUT — sensor not ready after 500 ms

      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

TIMEOUT_MS = 500

# Simulated sensor: becomes ready after this many polls.
# Cycles through values so some attempts succeed and some time out.
_READY_AFTER = [4, 99, 3, 99, 2]
_cycle_index = 0


def poll_sensor(poll_count: int) -> bool:
    """Check whether the sensor is ready.

    Args:
        poll_count: Number of polls completed so far.

    Returns:
        True when the sensor is ready.

    On a real board::

        return sensor_pin.value  # or status_register & READY_BIT
    """
    threshold = _READY_AFTER[_cycle_index % len(_READY_AFTER)]
    return poll_count >= threshold


def wait_for_sensor(timeout_ms: int) -> int:
    """Poll the sensor until ready or *timeout_ms* expires.

    Demonstrates ``ticks_add`` for computing a deadline and
    ``ticks_diff`` for checking it.

    Args:
        timeout_ms: Maximum time to wait in milliseconds.

    Returns:
        Elapsed time in ms on success, or ``-1`` on timeout.
    """
    # Record the start time and compute the absolute deadline.
    start = ticks_ms()
    deadline = ticks_add(start, timeout_ms)
    polls = 0

    # Read the clock fresh at the top of every iteration and test the
    # deadline on that value.  ticks_diff handles wraparound.  Checking a
    # timestamp captured at the end of the previous iteration (before the
    # poll + sleep) could report success after the deadline had already
    # passed.
    while True:
        now = ticks_ms()
        if ticks_diff(now, deadline) >= 0:
            return -1  # timed out

        elapsed = ticks_diff(now, start)
        if poll_sensor(polls):
            return elapsed

        print(f"    [{elapsed} ms] not ready...")
        polls += 1

        # Brief pause between polls.  On a real board you would
        # yield to the main loop or scheduler here instead.
        time.sleep(0.1)


print("Running timeout checks...\n")

while True:
    print(f"  Waiting for sensor ({TIMEOUT_MS} ms deadline)...")

    result = wait_for_sensor(TIMEOUT_MS)
    if result >= 0:
        print(f"    sensor ready after {result} ms\n")
    else:
        print(f"    TIMEOUT — sensor not ready after "
              f"{TIMEOUT_MS} ms\n")

    _cycle_index += 1

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo readable.
    time.sleep(1)
