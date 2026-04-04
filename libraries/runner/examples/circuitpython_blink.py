# requires: hardware
"""Runner LED blink — CircuitPython.

Toggles the onboard LED every 500 ms using a periodic runner task.
Drop this file onto your board as ``code.py``.

Wiring: none — uses the built-in LED (``board.LED``).

Runs on CircuitPython.
"""

import board
import digitalio
from chumicro_runner import Runner

# Set up the onboard LED as a digital output.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def toggle_led(now_ms):
    """Toggle the LED state."""
    led.value = not led.value


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)

while True:
    runner.tick()

