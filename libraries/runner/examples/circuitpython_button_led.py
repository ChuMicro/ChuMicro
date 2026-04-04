# requires: hardware
"""Button-controlled LED — CircuitPython gate pattern.

Reads a button and toggles an LED using the runner's check/handle
gate pattern.  The runner calls ``check()`` every tick; when the
button is pressed, ``handle()`` fires and toggles the LED.

Setup:
1. Copy ``chumicro_runner`` and ``chumicro_timing`` to the ``lib/``
   folder on your board.
2. Wire a momentary button between ``board.D5`` and GND.
3. Save this file as ``code.py`` on the board.

Wiring:
- Button: one leg to ``D5``, other leg to ``GND``.
  The internal pull-up keeps ``D5`` high when the button is open.
- LED: uses the built-in LED (``board.LED``) — no extra wiring.

Runs on CircuitPython.
"""

import board
import digitalio
from chumicro_runner import Runner

# Set up the onboard LED.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# Set up a button with an internal pull-up resistor.
# Pressing the button connects D5 to GND → value goes False.
button = digitalio.DigitalInOut(board.D5)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP


class ButtonToggle:
    """Toggle an LED each time a button is pressed.

    Uses edge detection so the LED toggles once per press,
    not continuously while held.
    """

    def __init__(self):
        """Track the previous button state for edge detection."""
        self._was_pressed = False

    def check(self, now_ms):
        """Return True on the falling edge (button just pressed)."""
        pressed = not button.value  # active-low
        just_pressed = pressed and not self._was_pressed
        self._was_pressed = pressed
        return just_pressed

    def handle(self, now_ms):
        """Toggle the LED."""
        led.value = not led.value


runner = Runner()
runner.add(ButtonToggle())

while True:
    runner.tick()

