"""Multiple services — combining periodic, gate-based, and callable patterns.

Shows how different service patterns coexist in a single runner:

- A periodic health check (fires every 2 seconds)
- A motion detector using the object-based pattern (gate-based)
- A callable check function + handler (lambda-based)
- Runtime period changes via ``ServiceHandle``

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner


class MotionDetector:
    """PIR motion sensor — object-based gate service.

    ``service()`` performs a fast digital pin read via ``detect_motion()``.
    On a real board, this reads a GPIO input.  Here, motion is simulated
    by setting ``_pin_high`` from the main loop.
    """

    def __init__(self):
        """Create a detector.

        On a real board: self._pin = digitalio.DigitalInOut(board.D5)
        """
        self._pin_high = False  # simulated pin state

    def detect_motion(self):
        """Read the PIR sensor pin — fast digital read.

        On a real board: return self._pin.value
        This is exactly the kind of fast check that belongs in service().
        """
        return self._pin_high

    def service(self, now_ms):
        """Check for motion (fast pin read)."""
        return self.detect_motion()

    def handle(self, now_ms):
        """React to detected motion."""
        print(f"  [{now_ms} ms] MOTION detected!")
        self._pin_high = False  # PIR sensor resets after read


class LightSensor:
    """Ambient light sensor — demonstrates callable-based check.

    Used via lambdas in the callable registration pattern below.
    On a real board, ``read_level()`` would sample an ADC pin.
    """

    def __init__(self):
        """Create a sensor with a default bright reading."""
        self._level = 50  # simulated light level (0–100)

    def read_level(self):
        """Read ambient light level (0=dark, 100=bright).

        On a real board: return self._adc.value // 256
        """
        return self._level


def main():
    """Run multiple service patterns in a single loop."""
    runner = ServiceRunner()

    # 1. Periodic health check — fires every 2 seconds.
    runner.add_periodic(
        lambda now_ms: print(f"  [{now_ms} ms] health: OK"),
        period_ms=2000,
    )

    # 2. Object-based motion detector — checked every tick.
    detector = MotionDetector()
    runner.add(detector)

    # 3. Callable check + handler (light sensor).
    light = LightSensor()
    runner.add(
        lambda now_ms: light.read_level() < 20,
        handler=lambda now_ms: print(
            f"  [{now_ms} ms] lights ON (level={light.read_level()})"
        ),
    )

    # 4. Periodic data logger — we'll change its rate at runtime.
    log_handle = runner.add_periodic(
        lambda now_ms: print(f"  [{now_ms} ms] logging data..."),
        period_ms=5000,
    )

    print("Running services...\n")

    for i in range(40):
        # Simulate external events.
        if i == 8:
            detector._pin_high = True  # PIR sensor triggers
        if i == 16:
            light._level = 10  # it got dark
        if i == 24:
            light._level = 60  # bright again
        if i == 30:
            log_handle.set_period(2000)
            print("  >> logging rate increased to 2 s")

        runner.service_once()
        time.sleep(0.1)  # simulate other work between ticks

    print("\nDone.")


if __name__ == "__main__":
    main()

