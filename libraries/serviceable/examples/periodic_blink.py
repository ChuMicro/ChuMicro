"""Periodic LED blink — simplest serviceable pattern.

Registers a handler that toggles a simulated LED every 500 ms.
The main loop calls ``service_once()`` frequently; the runner's
period gate ensures the handler fires only twice per second.

No service class needed — just a callback and a period.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner

led_state = False


def toggle_led(now_ms):
    """Toggle the simulated LED and print its state."""
    global led_state  # noqa: PLW0603
    led_state = not led_state
    state = "ON" if led_state else "OFF"
    print(f"  [{now_ms} ms] LED {state}")


def main():
    """Blink a simulated LED every 500 ms for 5 seconds."""
    runner = ServiceRunner()
    runner.add_periodic(toggle_led, period_ms=500)

    print("Blinking LED (5 seconds)...\n")

    end_time = time.monotonic() + 5
    while time.monotonic() < end_time:
        runner.service_once()
        time.sleep(0.05)  # simulate other work between ticks

    print("\nDone.")


if __name__ == "__main__":
    main()

