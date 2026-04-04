# requires: hardware
"""Button-controlled LED — MicroPython gate pattern.

Reads a button and toggles an LED using the runner's check/handle
gate pattern.  The runner calls ``check()`` every tick; when the
button is pressed, ``handle()`` fires and toggles the LED.

Setup:
1. Copy ``chumicro_runner`` and ``chumicro_timing`` to the board
   (e.g., via ``mpremote``).
2. Wire a momentary button between GPIO 0 and GND.
3. Save this file as ``main.py`` on the board.

Wiring:
- Button: one leg to ``GPIO 0``, other leg to ``GND``.
  The internal pull-up keeps the pin high when the button is open.
- LED: uses pin 2, the built-in LED on most ESP32 dev boards.
  Change ``Pin(2)`` to match your board.

Runs on MicroPython.
"""

from chumicro_runner import Runner
from machine import Pin

# Set up the onboard LED.
led = Pin(2, Pin.OUT)

# Set up a button with an internal pull-up resistor.
# Pressing the button connects GPIO 0 to GND → value goes 0.
button = Pin(0, Pin.IN, Pin.PULL_UP)


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
        pressed = not button.value()  # active-low
        just_pressed = pressed and not self._was_pressed
        self._was_pressed = pressed
        return just_pressed

    def handle(self, now_ms):
        """Toggle the LED."""
        led.value(not led.value())


runner = Runner()
runner.add(ButtonToggle())

while True:
    runner.tick()

