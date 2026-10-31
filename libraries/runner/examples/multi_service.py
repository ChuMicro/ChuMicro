"""Run two services and two timed jobs side by side, each at its own pace.

Four jobs share one loop, forever:

- a health line every 2 s (a timed job),
- a motion alarm that reads its sensor every 100 ms (a service),
- a night light that reads its light sensor every 500 ms (a service),
- a log line every 5 s (a timed job).

The sensors are pretend.  The motion sensor trips every 8 s, and the room
goes dark from 4 s to 8 s of every 10 s, so the night light switches on and
off on that schedule.  Each job runs on its own period, and none of them
waits for another.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python multi_service.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.

Example output::

    Running four jobs...
    health: OK
    health: OK
    lights on
    logging data
    health: OK
    health: OK
    lights off
    MOTION: alarm
    logging data
    health: OK
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner


class MotionAlarm:
    """Sound the alarm when the motion sensor trips."""

    def __init__(self) -> None:
        self.reads = 0

    def detect_motion(self) -> bool:
        """Read the pretend sensor: it trips on every 80th read, every 8 s at 100 ms.

        On a board, return the sensor's pin instead, such as ``pir.value``.
        """
        self.reads += 1
        return self.reads % 80 == 0

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the sensor has tripped."""
        return self.detect_motion()

    def handle(self, now_ms: int) -> None:
        """Sound the alarm."""
        print("MOTION: alarm")


class NightLight:
    """Switch the lights on when the room goes dark and off when it brightens."""

    def __init__(self) -> None:
        self.reads = 0
        self.lights_on = False

    def read_light_level(self) -> int:
        """Read the pretend sensor, 0 dark to 100 bright: dark for reads 8 to 15 of every 20.

        On a board, return the sensor's reading instead, such as an analog pin's value.
        """
        self.reads += 1
        if 8 <= self.reads % 20 < 16:
            return 12
        return 60

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the lights are in the wrong state for the room."""
        dark = self.read_light_level() < 20
        return dark != self.lights_on

    def handle(self, now_ms: int) -> None:
        """Flip the lights."""
        self.lights_on = not self.lights_on
        print("lights on" if self.lights_on else "lights off")


def report_health(now_ms: int) -> None:
    """Print a health line."""
    print("health: OK")


def log_data(now_ms: int) -> None:
    """Print a log line."""
    print("logging data")


runner = Runner()
runner.add_periodic(report_health, period_ms=2000)   # every 2 s
runner.add(MotionAlarm(), period_ms=100)              # read the motion sensor every 100 ms
runner.add(NightLight(), period_ms=500)               # read the light sensor every 500 ms
runner.add_periodic(log_data, period_ms=5000)         # every 5 s

print("Running four jobs...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
