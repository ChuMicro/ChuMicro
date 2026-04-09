"""Button-controlled LED — CircuitPython gate pattern.

Reads a button and toggles an LED using the runner's check/handle
gate pattern.  The runner calls ``check()`` every tick; when the
button is pressed, ``handle()`` fires and toggles the LED.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro-runner`` or copy both packages
   to ``lib/``).
2. Wire a momentary button between ``D5`` and ``GND``.  The
   internal pull-up keeps ``D5`` high when the button is open.
   The built-in LED (``board.LED``) needs no extra wiring.
3. Save this file as ``code.py`` on the board.


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

    def __init__(self) -> None:
        """Track the previous button state for edge detection."""
        self._was_pressed = False

    def check(self, now_ms: int) -> bool:
        """Return True on the falling edge (button just pressed)."""
        pressed = not button.value  # active-low
        just_pressed = pressed and not self._was_pressed
        self._was_pressed = pressed
        return just_pressed

    def handle(self, now_ms: int) -> None:
        """Toggle the LED."""
        led.value = not led.value


runner = Runner()
runner.add(ButtonToggle())

while True:
    runner.tick()
