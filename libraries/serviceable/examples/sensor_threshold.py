"""Sensor threshold alert — gate-based service pattern.

A temperature sensor reads its hardware in ``service()`` and fires
``handle()`` when the reading exceeds a threshold.  This demonstrates
the gate-based pattern: ``service()`` performs a fast hardware check
and returns whether the handler should fire.

On a real board, ``read_temperature()`` would be a fast I2C or ADC
read.  Here it pulls from a simulated sequence.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner


class TemperatureSensor:
    """Alert when temperature exceeds a threshold.

    ``service()`` calls ``read_temperature()`` — a fast, non-blocking
    sensor read — and returns True when the reading exceeds the
    threshold.  ``handle()`` reacts (here it prints; on a real board
    it might activate a fan or send a network alert).
    """

    def __init__(self, threshold=30.0):
        """Create a sensor with the given alert threshold (°C)."""
        self._threshold = threshold
        self._last_reading = 0.0
        # Simulated readings for this example.
        self._sim_readings = iter(
            [22.0, 25.0, 28.0, 31.0, 35.0, 29.0, 33.0, 27.0]
        )

    def read_temperature(self):
        """Read the current temperature from hardware.

        On a real board this would be a fast I2C or ADC read, e.g.:
            return self._i2c_device.temperature

        Fast sensor reads are exactly the kind of operation that
        belongs in ``service()``.
        """
        return next(self._sim_readings, self._last_reading)

    def service(self, now_ms):
        """Read the sensor and check against the threshold."""
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms):
        """React to a threshold breach."""
        print(
            f"  [{now_ms} ms] ALERT: {self._last_reading}°C "
            f"exceeds {self._threshold}°C"
        )


def main():
    """Simulate a temperature sensor that triggers on threshold breach."""
    runner = ServiceRunner()
    sensor = TemperatureSensor(threshold=30.0)

    # Check the sensor every 500 ms.
    runner.add(sensor, period_ms=500)

    print("Monitoring temperature (simulated)...\n")

    end_time = time.monotonic() + 5
    while time.monotonic() < end_time:
        runner.service_once()
        time.sleep(0.1)  # simulate other work between ticks

    print("\nDone.")


if __name__ == "__main__":
    main()

