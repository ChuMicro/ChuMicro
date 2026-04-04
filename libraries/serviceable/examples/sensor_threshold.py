"""Sensor threshold alert — gate-based service pattern.

A simulated temperature sensor checks on each tick whether the reading
exceeds a threshold.  When it does, the handler fires.  Demonstrates
the gate-based registration pattern: the service decides IF the handler
should fire; the runner decides WHEN to check.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner


class TemperatureSensor:
    """Simulated sensor that alerts when temperature exceeds a threshold.

    Object-based service: ``.service(now_ms)`` returns ``True`` when the
    reading exceeds the threshold, and ``.handle(now_ms)`` reacts to it.
    """

    def __init__(self, threshold=30.0):
        """Create a sensor with the given alert threshold (°C)."""
        self._threshold = threshold
        self.reading = 20.0

    def service(self, now_ms):
        """Return True when the current reading exceeds the threshold."""
        return self.reading > self._threshold

    def handle(self, now_ms):
        """React to a threshold breach."""
        print(
            f"  [{now_ms} ms] ALERT: {self.reading}°C "
            f"exceeds {self._threshold}°C"
        )


def main():
    """Simulate a temperature sensor that triggers on threshold breach."""
    runner = ServiceRunner()
    sensor = TemperatureSensor(threshold=30.0)

    # Check the sensor every 500 ms.
    runner.add(sensor, period_ms=500)

    print("Monitoring temperature (simulated)...\n")

    readings = [22.0, 25.0, 28.0, 31.0, 35.0, 29.0, 33.0, 27.0]
    for reading in readings:
        sensor.reading = reading
        print(f"  sensor reads {reading}°C")
        runner.service_once()
        time.sleep(0.5)

    print("\nDone.")


if __name__ == "__main__":
    main()

