"""Periodic and gate-based handlers — no component class needed.

Demonstrates the three registration paths on ``ServiceRunner``:

1. **Periodic** — ``add_periodic(handler, period_ms)``: fires a callback
   every *period_ms* milliseconds.
2. **Gate-based** — ``add(service, handler=fn)``: calls
   ``service.service(now_ms)``, fires *fn* when the service returns True.
3. **Event-based** — ``add(service)``: the existing event-driven pattern
   (shown in ``hello.py``).

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner


class ThresholdSensor:
    """Dummy sensor that fires when a threshold is exceeded.

    A gate-based service: ``service(now_ms)`` returns ``True`` when the
    reading crosses a threshold, ``False`` otherwise.
    """

    def __init__(self, threshold=10):
        """Create a sensor with the given threshold."""
        self._threshold = threshold
        self._count = 0

    def service(self, now_ms):
        """Simulate a reading; return True when threshold is exceeded."""
        self._count += 1
        return self._count % self._threshold == 0


def main():
    """Run periodic and gate-based handlers through the dispatch loop."""
    runner = ServiceRunner()

    # Periodic: blink every 500 ms.
    blink_handle = runner.add_periodic(
        lambda now_ms: print(f"  [{now_ms} ms] blink!"),
        period_ms=500,
    )
    print(f"Periodic: {blink_handle}")

    # Gate-based: fire when the sensor crosses its threshold.
    sensor = ThresholdSensor(threshold=10)
    sensor_handle = runner.add(
        sensor,
        handler=lambda now_ms: print(f"  [{now_ms} ms] threshold reached!"),
    )
    print(f"Gate-based: {sensor_handle}")

    print()
    print("Running (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
