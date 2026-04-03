"""Heartbeat blink — the embedded hello world.

Prints a message once per second using a non-blocking heartbeat timer.
Runs on CPython, MicroPython, and CircuitPython without modification.

On a real board, replace the print() with an LED toggle.
"""

import time

from chumicro_timing import Heartbeat


def main():
    """Run a one-second heartbeat loop until interrupted."""
    heartbeat = Heartbeat(period_ms=1000)

    print("Running heartbeat blink (Ctrl+C to stop)...")

    try:
        while True:
            if heartbeat.poll():
                print("beat!")

            # Simulate other work or yield time.
            # On a real board this would be your main loop body.
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
