"""Freeze one argument to a function using partial.

Shows the simplest use of ``partial``: binding a positional argument
so the returned callable needs fewer parameters.

Example output::

    pin 13 → 50%
    pin 13 → 100%

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_compat.functools import partial


def set_led(pin: int, brightness: int) -> None:
    """Set an LED pin to a brightness level.

    Args:
        pin: GPIO pin number.
        brightness: Brightness percentage (0–100).
    """
    print(f"pin {pin} → {brightness}%")


# Freeze the pin number, so set_status_led only needs brightness.
set_status_led = partial(set_led, 13)

set_status_led(50)
set_status_led(100)
