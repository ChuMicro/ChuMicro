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
    """Simulated motion detector — object-based gate service.

    ``.service()`` returns ``True`` when motion is detected.
    ``.handle()`` logs the event and resets the flag.
    """

    def __init__(self):
        """Create a detector with no motion detected."""
        self.motion_detected = False

    def service(self, now_ms):
        """Return True when motion is currently detected."""
        return self.motion_detected

    def handle(self, now_ms):
        """Log the motion event and reset the flag."""
        print(f"  [{now_ms} ms] MOTION detected!")
        self.motion_detected = False


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

    # 3. Callable check + handler (simulated light sensor).
    light_level = [50]  # mutable so lambdas can read it
    runner.add(
        lambda now_ms: light_level[0] < 20,
        handler=lambda now_ms: print(
            f"  [{now_ms} ms] lights ON (level={light_level[0]})"
        ),
    )

    # 4. Periodic data logger — we'll change its rate at runtime.
    log_handle = runner.add_periodic(
        lambda now_ms: print(f"  [{now_ms} ms] logging data..."),
        period_ms=5000,
    )

    print("Running services...\n")

    for i in range(20):
        # Simulate external events.
        if i == 3:
            detector.motion_detected = True
        if i == 8:
            light_level[0] = 10  # dark — trigger light handler
        if i == 10:
            light_level[0] = 60  # bright again
        if i == 12:
            # Speed up logging at runtime.
            log_handle.set_period(2000)
            print("  >> logging rate increased to 2 s")

        runner.service_once()
        time.sleep(0.5)

    print("\nDone.")


if __name__ == "__main__":
    main()

