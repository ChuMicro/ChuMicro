"""Timeout check using tick functions directly.

Shows how to use ``ticks_ms`` / ``ticks_diff`` / ``ticks_add`` for
deadline enforcement — the kind of custom timing logic that doesn't
fit the ``Heartbeat`` pattern.

The loop polls a simulated sensor until it gets a "ready" reading or
the deadline expires.  On a real board, ``poll_sensor()`` would be a
fast non-blocking check (GPIO pin, status register, etc.).

Example output::

    Waiting for sensor (500 ms deadline)...

      [120 ms] not ready...
      [241 ms] not ready...
      [362 ms] not ready...
      [480 ms] sensor ready! (took 480 ms)

    Waiting for sensor (500 ms deadline)...

      [121 ms] not ready...
      [240 ms] not ready...
      [361 ms] not ready...
      [482 ms] not ready...
      TIMEOUT after 500 ms — sensor never became ready

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


def main():
    """Run repeated deadline-enforced sensor polls."""
    global _cycle_index  # noqa: PLW0603

    print("Running timeout checks (Ctrl+C to stop)...\n")

    try:
        while True:
            start = ticks_ms()
            deadline = ticks_add(start, TIMEOUT_MS)
            polls = 0

            print(f"  Waiting for sensor ({TIMEOUT_MS} ms deadline)...\n")

            while True:
                now = ticks_ms()
                elapsed = ticks_diff(now, start)

                if poll_sensor(polls):
                    print(f"    [{elapsed} ms] sensor ready! "
                          f"(took {elapsed} ms)\n")
                    break

                if ticks_diff(now, deadline) >= 0:
                    print(f"    TIMEOUT after {TIMEOUT_MS} ms "
                          f"— sensor never became ready\n")
                    break

                print(f"    [{elapsed} ms] not ready...")
                polls += 1
                time.sleep(0.1)

            _cycle_index += 1
            time.sleep(1)  # pause between attempts
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
