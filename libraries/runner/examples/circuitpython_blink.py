"""Runner LED blink — CircuitPython.

Toggles the onboard LED every 500 ms using a periodic runner task.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro-runner`` or copy both packages
   to ``lib/``).
2. No extra wiring — uses the built-in LED (``board.LED``).
3. Save this file as ``code.py`` on the board.

Runs on CircuitPython.
"""

import board
import digitalio
from chumicro_runner import Runner

# Set up the onboard LED as a digital output.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def toggle_led(now_ms: int) -> None:
    """Toggle the LED state."""
    led.value = not led.value


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)

while True:
    runner.tick()
