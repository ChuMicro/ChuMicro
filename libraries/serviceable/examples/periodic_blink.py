"""Periodic LED blink — simplest serviceable pattern.

Registers a handler that fires every 500 ms, simulating an LED toggle.
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

    print("Blinking LED (5 seconds)...")

    for _ in range(10):
        runner.service_once()
        time.sleep(0.5)

    print("Done.")


if __name__ == "__main__":
    main()

