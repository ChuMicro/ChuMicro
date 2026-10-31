"""Toggle the built-in LED each time you press a button.

Every press flips the LED and prints a line on the serial console.  Holding
the button down counts as one press.  The program keeps watching the button
forever.

``ButtonToggle`` is a service: the runner calls ``check()`` every 20 ms to
ask "was the button just pressed?", and calls ``handle()`` to flip the LED
only when the answer is yes.  Reading the button every 20 ms also debounces
it: a switch stops bouncing well inside that window, so one press reads as
one press.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro_runner``, or copy both packages into ``lib/``).
2. Wire a push button between a GPIO pin and GND.  The pin's internal
   pull-up holds it high until the button pulls it low.  Boards listed in
   ``BOARD_BUTTON_PINS`` find their pin on their own; on any other board, set
   ``BUTTON_PIN`` to the pin name, such as ``"D5"`` or ``"GP14"``.
3. Save this file as ``code.py`` on the board.

Example output::

    Press the button to toggle the LED.
    press 1: LED on
    press 2: LED off
    press 3: LED on
    ...

Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_button_led.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_runner import Runner

# The pin your button is wired to, by its name on the board module.
# Leave it empty to look your board up in BOARD_BUTTON_PINS.
BUTTON_PIN = ""

# Button pins for boards this example has been wired up on, keyed by
# board.board_id (print it at the REPL with: import board; board.board_id).
BOARD_BUTTON_PINS = {
    "raspberry_pi_pico_w": "GP14",
    "raspberry_pi_pico2_w": "GP14",
    "lolin_s2_mini": "D5",
    "lolin_s2_pico": "D5",
    "adafruit_feather_esp32s2": "BUTTON",
    "adafruit_feather_esp32s3_4mbflash_2mbpsram": "BUTTON",
}


def find_button_pin():
    """Return the ``board`` pin named by BUTTON_PIN or by this board's BOARD_BUTTON_PINS entry."""
    pin_name = BUTTON_PIN or BOARD_BUTTON_PINS.get(board.board_id)
    if not pin_name:
        raise RuntimeError(
            f"no button pin known for {board.board_id!r}: set BUTTON_PIN "
            f"at the top of this file, for example BUTTON_PIN = \"D5\"",
        )
    return getattr(board, pin_name)


led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

button = digitalio.DigitalInOut(find_button_pin())
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP


class ButtonToggle:
    """Flip the LED once per button press."""

    def __init__(self) -> None:
        self.was_pressed = False
        self.presses = 0

    def check(self, now_ms: int) -> bool:
        """Return ``True`` only on the read where the button goes from up to down.

        The runner passes ``now_ms``, the time of the current tick in
        milliseconds.  This service has no use for it.
        """
        pressed = not button.value   # the pull-up reads False while the button is held
        just_pressed = pressed and not self.was_pressed
        self.was_pressed = pressed
        return just_pressed

    def handle(self, now_ms: int) -> None:
        """Flip the LED and print the press count."""
        led.value = not led.value
        self.presses += 1
        state = "on" if led.value else "off"
        print(f"press {self.presses}: LED {state}")


runner = Runner()
runner.add(ButtonToggle(), period_ms=20)   # read the button every 20 ms

print("Press the button to toggle the LED.")

while True:
    now_ms = runner.tick()   # check every service that is due right now
    runner.wait(now_ms)      # sleep until the next button read is due
