"""Periodic LED blink — simplest runner example.

Toggles a simulated LED every 500 ms.  On a real board, replace
the ``print`` with a pin toggle (``led.value = not led.value``).

Example output::

    Blinking... (Ctrl+C to stop)

    LED ON
    LED OFF
    LED ON
    LED OFF
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_runner import Runner

led_state = False


def toggle_led(now_ms):
    """Toggle the LED."""
    global led_state  # noqa: PLW0603
    led_state = not led_state
    print(f"  LED {'ON' if led_state else 'OFF'}")


def main():
    """Blink an LED every 500 ms."""
    runner = Runner()
    runner.add_periodic(toggle_led, period_ms=500)

    print("Blinking... (Ctrl+C to stop)\n")

    while True:
        runner.tick()
        time.sleep(0.05)


if __name__ == "__main__":
    main()

