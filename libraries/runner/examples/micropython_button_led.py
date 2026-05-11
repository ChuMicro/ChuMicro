"""Button-controlled LED — MicroPython gate pattern.

Reads a button and toggles an LED using the runner's check/handle
gate pattern.  The runner calls ``check()`` every tick; when the
button is pressed, ``handle()`` fires and toggles the LED.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``mpremote mip install chumicro-runner`` or copy both
   packages to the board).
2. Wire a momentary button between ``GPIO 0`` and ``GND``.
   The internal pull-up keeps the pin high when the button is
   open.  Pin 2 (built-in LED on most ESP32 boards) needs no
   extra wiring.  Change ``Pin(2)`` to match your board.
3. Save this file as ``main.py`` on the board.


Runs on MicroPython.
"""

#: MicroPython-only — uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_button_led.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

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

    def __init__(self) -> None:
        """Track the previous button state for edge detection."""
        self._was_pressed = False

    def check(self, now_ms: int) -> bool:
        """Return True on the falling edge (button just pressed).

        Args:
            now_ms: Current tick value.

        Returns:
            True if the button was just pressed.
        """
        pressed = not button.value()  # active-low
        just_pressed = pressed and not self._was_pressed
        self._was_pressed = pressed
        return just_pressed

    def handle(self, now_ms: int) -> None:
        """Toggle the LED.

        Args:
            now_ms: Current tick value.
        """
        led.value(not led.value())


runner = Runner()
runner.add(ButtonToggle())

while True:
    runner.tick()
