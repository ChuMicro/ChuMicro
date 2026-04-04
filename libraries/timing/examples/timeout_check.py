"""Timeout check using tick functions directly.

Shows how to use ``ticks_ms`` / ``ticks_diff`` / ``ticks_add`` for
deadline enforcement — the kind of custom timing logic that doesn't
fit the ``Heartbeat`` pattern.

A ``wait_for_sensor()`` helper polls until a sensor is ready or a
deadline expires.  On a real board, ``poll_sensor()`` would be a fast
non-blocking check (GPIO pin, status register, etc.).

Example output::

    Running timeout checks (Ctrl+C to stop)...

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


def poll_sensor(poll_count):
    """Check whether the sensor is ready.

    On a real board::

        return sensor_pin.value  # or status_register & READY_BIT
    """
    threshold = _READY_AFTER[_cycle_index % len(_READY_AFTER)]
    return poll_count >= threshold


def wait_for_sensor(timeout_ms):
    """Poll the sensor until ready or *timeout_ms* expires.

    Returns the elapsed time in ms on success, or ``-1`` on timeout.
    Demonstrates ``ticks_add`` for computing a deadline and
    ``ticks_diff`` for checking it.
    """
    start = ticks_ms()
    deadline = ticks_add(start, timeout_ms)
    polls = 0
    now = start

    while ticks_diff(now, deadline) < 0:
        now = ticks_ms()
        elapsed = ticks_diff(now, start)

        if poll_sensor(polls):
            return elapsed

        print(f"    [{elapsed} ms] not ready...")
        polls += 1
        time.sleep(0.1)

    return -1


def main():
    """Run repeated deadline-enforced sensor polls."""
    global _cycle_index  # noqa: PLW0603

    print("Running timeout checks (Ctrl+C to stop)...\n")

    try:
        while True:
            print(f"  Waiting for sensor ({TIMEOUT_MS} ms deadline)...")

            result = wait_for_sensor(TIMEOUT_MS)
            if result >= 0:
                print(f"    sensor ready after {result} ms\n")
            else:
                print(f"    TIMEOUT — sensor not ready after "
                      f"{TIMEOUT_MS} ms\n")

            _cycle_index += 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
