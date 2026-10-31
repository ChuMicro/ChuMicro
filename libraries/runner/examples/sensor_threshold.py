"""Watch a temperature and print an alert whenever it runs over a limit.

Once a second the program reads a pretend sensor, and it prints an alert
each time the reading is above 30 C.  The readings cycle through a fixed
list, so alerts appear for two seconds out of every eight, forever.

``TemperatureAlarm`` is a service: an object with two methods the runner
calls for you.  ``check()`` reads the sensor and answers "is there anything
to do?".  ``handle()`` does it, and the runner calls it only on the ticks
where ``check()`` returned ``True``.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python sensor_threshold.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.
3. On a board with a real sensor, make ``read_temperature()`` return the
   sensor's reading, such as ``sensor.temperature`` from an Adafruit
   sensor driver.

Example output::

    Watching the temperature (alert above 30.0 C)...
    ALERT: 31.0 C is above the 30.0 C limit
    ALERT: 35.0 C is above the 30.0 C limit
    ALERT: 31.0 C is above the 30.0 C limit
    ALERT: 35.0 C is above the 30.0 C limit
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner

LIMIT_C = 30.0
READINGS = [22.0, 25.0, 28.0, 31.0, 35.0, 29.0, 24.0, 20.0]

reading_index = 0


def read_temperature() -> float:
    """Return the next pretend reading in degrees C, cycling through READINGS."""
    global reading_index
    value = READINGS[reading_index % len(READINGS)]
    reading_index += 1
    return value


class TemperatureAlarm:
    """Print an alert whenever the temperature is above ``limit_c``."""

    def __init__(self, limit_c: float) -> None:
        self.limit_c = limit_c
        self.reading = 0.0

    def check(self, now_ms: int) -> bool:
        """Read the sensor and return ``True`` when the reading is over the limit.

        The runner passes ``now_ms``, the time of the current tick in
        milliseconds.  This service has no use for it.
        """
        self.reading = read_temperature()
        return self.reading > self.limit_c

    def handle(self, now_ms: int) -> None:
        """Print the alert for the reading ``check()`` just took."""
        print(f"ALERT: {self.reading} C is above the {self.limit_c} C limit")


runner = Runner()
runner.add(TemperatureAlarm(LIMIT_C), period_ms=1000)   # check once a second

print(f"Watching the temperature (alert above {LIMIT_C} C)...")

while True:
    now_ms = runner.tick()   # check every service that is due right now
    runner.wait(now_ms)      # sleep until the next check is due
