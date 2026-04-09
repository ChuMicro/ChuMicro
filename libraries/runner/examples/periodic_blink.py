"""Periodic LED blink — simplest runner example.

Toggles a simulated LED every 500 ms.  On a real board, replace
the ``print`` with a pin toggle (``led.value = not led.value``).

Example output::

    Blinking...

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


def toggle_led(now_ms: int) -> None:
    """Toggle the LED.

    Args:
        now_ms: Current tick value.
    """
    global led_state  # noqa: PLW0603
    led_state = not led_state
    print(f"  LED {'ON' if led_state else 'OFF'}")


runner = Runner()

# add_periodic registers a handler that fires on a fixed schedule.
# The runner manages the timing internally — you just call tick()
# in your main loop.
runner.add_periodic(toggle_led, period_ms=500)

print("Blinking...\n")

while True:
    # tick() captures the current time, checks all registered
    # tasks, and fires any that are due.
    runner.tick()

    # In a real project, the rest of your main loop goes here —
    # reading sensors, checking buttons, etc.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.05)
