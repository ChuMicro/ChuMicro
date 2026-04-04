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
    heartbeat = Heartbeat(period_ms=1000)

    print("Running heartbeat blink (Ctrl+C to stop)...\n")

    try:
        while True:
            now = ticks_ms()
            if heartbeat.poll(now):
                # On a real board: led.value = not led.value
                print("  beat!")

            # Yield time — on a real board this is the rest of
            # your main loop.
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
