"""Sensor threshold alert: gate-based check/handle pattern.

``check()`` reads the sensor and returns whether the handler should
fire.  The runner calls ``check()`` on schedule.  When it returns
True, ``handle()`` fires.

On a real board, ``read_temperature()`` would be a fast I2C or ADC
read.  Here it cycles through simulated values.

Example output::

    Monitoring temperature...

    [3005 ms] ALERT: 31.0°C exceeds 30.0°C
    [4002 ms] ALERT: 35.0°C exceeds 30.0°C
    [11003 ms] ALERT: 31.0°C exceeds 30.0°C
    [12008 ms] ALERT: 35.0°C exceeds 30.0°C
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_runner import Runner

# Simulated readings that cycle.  Replace with hardware reads.
_READINGS = [22.0, 25.0, 28.0, 31.0, 35.0, 29.0, 24.0, 20.0]


class TemperatureSensor:
    """Alert when temperature exceeds a threshold.

    ``check()`` calls ``read_temperature()``, a fast non-blocking
    sensor read, and returns True when the threshold is exceeded.
    ``handle()`` reacts (print here, or a fan / network alert on a
    real board).
    """

    def __init__(self, threshold: float = 30.0) -> None:
        """Create a sensor with the given alert threshold (°C).

        Args:
            threshold: Temperature in °C above which ``check()``
                returns True.
        """
        self._threshold = threshold
        self._last_reading = 0.0
        self._index = 0

    def read_temperature(self) -> float:
        """Read temperature from hardware.

        Returns:
            Temperature in degrees Celsius.

        On a real board::

            return self._i2c_device.temperature
        """
        value = _READINGS[self._index % len(_READINGS)]
        self._index += 1
        return value

    def check(self, now_ms: int) -> bool:
        """Read the sensor and check against the threshold.

        Args:
            now_ms: Current tick value.

        Returns:
            True if the reading exceeds the threshold.
        """
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms: int) -> None:
        """React to a threshold breach.

        Args:
            now_ms: Current tick value.
        """
        print(
            f"  [{now_ms} ms] ALERT: {self._last_reading}°C "
            f"exceeds {self._threshold}°C"
        )


runner = Runner()
sensor = TemperatureSensor(threshold=30.0)

# Register the sensor as an object-based task.  The runner
# calls sensor.check(now_ms) on each tick (gated by period_ms).
# When check() returns True, sensor.handle(now_ms) fires.
runner.add(sensor, period_ms=1000)

print("Monitoring temperature...\n")

while True:
    runner.tick()

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.1)
