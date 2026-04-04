"""Heartbeat blink — the embedded hello world.

Prints a message once per second using a non-blocking heartbeat timer.
On a real board, replace the ``print`` with an LED toggle
(``led.value = not led.value``).

Example output::

    Running heartbeat blink (Ctrl+C to stop)...

    beat!
    beat!
    beat!
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Heartbeat, ticks_ms


def main():
    """Run a one-second heartbeat loop until interrupted."""
    # Create a heartbeat that fires once per second.
    heartbeat = Heartbeat(period_ms=1000)

    print("Running heartbeat blink (Ctrl+C to stop)...\n")

    try:
        # On embedded boards, code.py runs in an infinite loop.
        # This is the standard pattern for a main loop.
        while True:
            # Capture the current time once and pass it to all
            # timing checks.  This ensures consistent behavior
            # even if the checks take time to execute.
            now = ticks_ms()

            # poll() returns True once per period and advances
            # the timer.  It returns False on every other call.
            if heartbeat.poll(now):
                # On a real board: led.value = not led.value
                print("  beat!")

            # Small sleep to avoid busy-spinning on CPython.
            # On a real board you would do other work here
            # instead of sleeping — read sensors, check buttons,
            # update displays, etc.
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
