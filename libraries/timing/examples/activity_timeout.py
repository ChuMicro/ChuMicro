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


def read_button():
    """Check whether the user pressed a button.

    On a real board::

        return not button_pin.value   # active-low button
    """
    return False


def main():
    """Run an activity-timeout loop."""
    # Use a Heartbeat as an inactivity timer.  When the user does
    # something, call reset() to restart the countdown.  When the
    # period elapses without a reset, the timeout has fired.
    timeout = Heartbeat(period_ms=500)
    tick_count = 0

    print("Monitoring activity (Ctrl+C to stop)...\n")

    try:
        while True:
            now = ticks_ms()

            # Simulate intermittent button presses: active for the
            # first 3 ticks of every 11-tick cycle, idle otherwise.
            active = tick_count % 11 < 3 or read_button()
            tick_count += 1

            if active:
                # Any activity resets the countdown to zero.
                timeout.reset(now)
                print("  [tick] activity detected — resetting timeout")
            elif timeout.is_due(now):
                # is_due() checks whether the period has elapsed but
                # does NOT advance the timer (unlike poll()).  This
                # means it will keep returning True on every tick
                # until something calls reset().
                print(
                    f"  [tick] TIMEOUT: no activity for "
                    f"{timeout.period_ms} ms"
                )
            else:
                print("  [tick] idle...")

            # Sleep between ticks.  On a real board this would be
            # replaced by other work in the main loop.
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

