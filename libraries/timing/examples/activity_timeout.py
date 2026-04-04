"""Activity timeout — reset and peek without consuming.

Demonstrates ``is_due()`` and ``reset()`` for an inactivity-timeout
pattern.  ``is_due()`` checks whether the period has elapsed *without*
advancing the timer (unlike ``poll()`` which resets on fire).
``reset()`` restarts the countdown — call it whenever activity occurs.

This pattern is common for screen-off timers, idle disconnect, or
auto-sleep features.

Example output::

    Monitoring activity (Ctrl+C to stop)...

      [tick] activity detected — resetting timeout
      [tick] activity detected — resetting timeout
      [tick] idle...
      [tick] idle...
      [tick] idle...
      [tick] TIMEOUT: no activity for 500 ms
      [tick] activity detected — resetting timeout
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Heartbeat, ticks_ms

# Simulated activity: True for the first 3 checks, then False for 8,
# then repeats.
_ACTIVITY = [True, True, True] + [False] * 8
_activity_index = 0


def check_activity():
    """Check whether user activity occurred.

    On a real board: ``return button.value or touch.touched``
    """
    global _activity_index  # noqa: PLW0603
    result = _ACTIVITY[_activity_index % len(_ACTIVITY)]
    _activity_index += 1
    return result


def main():
    """Run an activity-timeout loop."""
    timeout = Heartbeat(period_ms=500)

    print("Monitoring activity (Ctrl+C to stop)...\n")

    try:
        while True:
            now = ticks_ms()

            if check_activity():
                timeout.reset(now)
                print("  [tick] activity detected — resetting timeout")
            elif timeout.is_due(now):
                # Peek: is_due() does not advance the timer.
                # We report timeout every tick until activity resumes.
                print(
                    f"  [tick] TIMEOUT: no activity for "
                    f"{timeout.period_ms} ms"
                )
            else:
                print("  [tick] idle...")

            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

