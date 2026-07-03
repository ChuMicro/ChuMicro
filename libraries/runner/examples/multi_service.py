"""Multiple services: combining patterns in one runner (advanced).

Shows how object-based, callable, and periodic registration patterns
coexist in a single ``Runner``:

- **Periodic** health check (every 2 s)
- **Object-based** motion detector (gate-based, checked every tick)
- **Callable** check + handler (light sensor)
- **Periodic** data logger (every 5 s)

All simulation lives inside the task objects.  On a real board,
``detect_motion()`` and ``read_level()`` would read GPIO/ADC pins.

Example output::

    Running services...

    [2005 ms] health: OK
    [4001 ms] health: OK
    [4102 ms] lights ON (level=12)
    [4204 ms] lights ON (level=12)
    ...
    [5003 ms] logging data
    [6001 ms] health: OK
    [6001 ms] lights ON (level=12)
    ...
    [8005 ms] MOTION — activating alarm
    [8005 ms] health: OK
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_runner import Runner


class MotionDetector:
    """PIR motion sensor as an object-based gate task.

    ``check()`` performs a fast digital pin read via
    ``detect_motion()``.  On a real board this reads a GPIO input.
    Here it simulates occasional triggers.
    """

    def __init__(self) -> None:
        """Create a detector.

        On a real board: ``self._pin = digitalio.DigitalInOut(board.D5)``
        """
        self._check_count = 0

    def detect_motion(self) -> bool:
        """Read the PIR sensor pin (fast digital read).

        Returns:
            True if motion is detected.

        On a real board: ``return self._pin.value``
        """
        # Simulated: triggers every ~80 checks (~8 s at 0.1 s ticks).
        self._check_count += 1
        return self._check_count % 80 == 0

    def check(self, now_ms: int) -> bool:
        """Check for motion (fast pin read).

        Args:
            now_ms: Current tick value.

        Returns:
            True if motion is detected.
        """
        return self.detect_motion()

    def handle(self, now_ms: int) -> None:
        """React to detected motion.

        Args:
            now_ms: Current tick value.
        """
        print(f"  [{now_ms} ms] MOTION — activating alarm")


class LightSensor:
    """Ambient light sensor, registered with the callable pattern.

    On a real board, ``read_level()`` would sample an ADC pin.
    Here it simulates a dark period so the light handler fires.
    """

    def __init__(self) -> None:
        """Create a sensor with a default bright reading."""
        self._check_count = 0

    def read_level(self) -> int:
        """Read ambient light level (0=dark, 100=bright).

        Returns:
            Light level reading.

        On a real board: ``return self._adc.value // 256``
        """
        # Simulated: dark for checks 40–80 (~4–8 s), bright otherwise.
        self._check_count += 1
        if 40 <= self._check_count <= 80:
            return 12
        return 60


runner = Runner()

# 1. Periodic health check, fires every 2 seconds.
runner.add_periodic(
    lambda now_ms: print(f"  [{now_ms} ms] health: OK"),
    period_ms=2000,
)

# 2. Object-based motion detector, checked every tick.
runner.add(MotionDetector())

# 3. Handler-only with the gate inside (light sensor).
light = LightSensor()


def lights_on_when_dark(now_ms):
    if light.read_level() < 20:
        print(f"  [{now_ms} ms] lights ON (level={light.read_level()})")


runner.add(handler=lights_on_when_dark)

# 4. Periodic data logger.
runner.add_periodic(
    lambda now_ms: print(f"  [{now_ms} ms] logging data"),
    period_ms=5000,
)

print("Running services...\n")

while True:
    # tick() checks every registered task (periodic, object-based,
    # callable) then fires any whose conditions are met.
    runner.tick()

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.1)
