"""Button-controlled LED: CircuitPython gate pattern.

Reads a button and toggles an LED using the runner's check/handle
gate pattern.  The runner calls ``check()`` every tick.  When the
button is pressed, ``handle()`` fires and toggles the LED.  Prints
a startup banner and a line on every accepted press so a serial
console (or a sweep harness) can verify the loop without a probe.

Example output::

    Button toggle — press button to flip the LED.

      [  815 ms] press → toggle
      [ 1407 ms] press → toggle
      ...

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro_runner`` or copy both packages
   to ``lib/``).
2. Wire a momentary button between the chosen GPIO and **GND**.
   The internal pull-up keeps the pin high when the button is
   open.  The built-in LED (``board.LED``) needs no extra wiring.
3. Save this file as ``code.py`` on the board.


Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_button_led.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_runner import Runner

# Set BUTTON_PIN to the pin attribute on the `board` module
# (e.g. "D5", "GP14", "BUTTON") to override autodetection.
# Leave empty to look up your board in BOARD_BUTTON_PINS below.
BUTTON_PIN = ""

# Per-board fallback used when BUTTON_PIN is empty.  Key is the
# string ``board.board_id`` returns on each board (find yours
# at the REPL with ``import board; print(board.board_id)``).
# One entry per line.  Add your board if it isn't listed.
BOARD_BUTTON_PINS = {
    "raspberry_pi_pico_w":     "GP14",
    "raspberry_pi_pico2_w":    "GP14",
    "lolin_s2_mini":           "D5",
    "lolin_s2_pico":           "D5",
    "adafruit_feather_esp32s2":               "BUTTON",
    "adafruit_feather_esp32s3_4mbflash_2mbpsram": "BUTTON",
}


def _resolve_button_pin():
    """Return the ``board`` attribute for the configured button pin."""
    pin_name = BUTTON_PIN or BOARD_BUTTON_PINS.get(board.board_id)
    if not pin_name:
        raise RuntimeError(
            f"no button pin for board {board.board_id!r}: set BUTTON_PIN "
            f"at the top of this file (e.g. \"D5\") or add an entry to "
            f"BOARD_BUTTON_PINS.",
        )
    pin = getattr(board, pin_name, None)
    if pin is None:
        raise RuntimeError(
            f"board has no pin named {pin_name!r}: check your "
            f"BUTTON_PIN setting / BOARD_BUTTON_PINS mapping.",
        )
    return pin


# Set up the onboard LED.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = digitalio.DigitalInOut(_resolve_button_pin())
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
        """Return True on the falling edge (button just pressed).

        Args:
            now_ms: Current tick value.

        Returns:
            True if the button was just pressed.
        """
        pressed = not button.value  # active-low
        just_pressed = pressed and not self._was_pressed
        self._was_pressed = pressed
        return just_pressed

    def handle(self, now_ms: int) -> None:
        """Toggle the LED and print a marker line.

        Args:
            now_ms: Current tick value.
        """
        led.value = not led.value
        print(f"  [{now_ms:>5} ms] press → toggle")


runner = Runner()
runner.add(ButtonToggle())

print("Button toggle — press button to flip the LED.\n")

while True:
    runner.tick()
