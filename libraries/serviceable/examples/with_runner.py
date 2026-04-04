"""Shared-timestamp loop — using ServiceRunner.

Same result as manual_loop.py, but ServiceRunner handles the timestamp
capture.  As your application grows, active components (MQTT, sensors)
can be registered with the runner and will be serviced automatically.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner
from chumicro_timing import Heartbeat


def main():
    """Run two heartbeats via ServiceRunner until interrupted."""
    led_beat = Heartbeat(period_ms=500)
    report_beat = Heartbeat(period_ms=3000)

    runner = ServiceRunner()

    print("Running with ServiceRunner (Ctrl+C to stop)...")

    try:
        while True:
            # Runner captures ticks_ms() once and returns the shared timestamp.
            now = runner.tick()

            if led_beat.poll(now):
                print("  blink!")
            if report_beat.poll(now):
                print("  sending report...")

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

