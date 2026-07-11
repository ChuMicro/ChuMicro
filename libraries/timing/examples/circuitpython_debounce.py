"""Button debounce — CircuitPython.

Reads a physical button with software debounce using ``ticks_ms``
and ``ticks_diff``.  Toggles the onboard LED on each accepted press.
Prints a startup banner and a line on every accepted press so a serial
console (or a sweep harness) can verify the loop without a probe.

Example output::

    Button debounce — press button to flip the LED.

      [  815 ms] press → toggle
      [ 1407 ms] press → toggle
      ...

Setup:
1. Install ``chumicro_timing`` (``circup install chumicro_timing``
   or copy the package to ``lib/``).
2. Wire a momentary button between the chosen GPIO and **GND**;
   the internal pull-up is enabled below.  Many boards (Feather,
   QT Py, Metro) expose the built-in user button as
   ``board.BUTTON`` — see ``BOARD_BUTTON_PINS`` below.
3. Save this file as ``code.py`` on the board.

Runs on CircuitPython.
"""

#: CircuitPython-only — uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_debounce.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_timing import ticks_diff, ticks_ms

DEBOUNCE_MS = 20

# Set BUTTON_PIN to the pin attribute on the `board` module
# (e.g. "D5", "GP14", "BUTTON") to override autodetection.
# Leave empty to look up your board in BOARD_BUTTON_PINS below.
BUTTON_PIN = ""

# Per-board fallback used when BUTTON_PIN is empty.  Key is the
# string ``board.board_id`` returns on each board (find yours
# at the REPL with ``import board; print(board.board_id)``).
# One entry per line — add your board if it isn't listed.
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
            f"no button pin for board {board.board_id!r} — set BUTTON_PIN "
            f"at the top of this file (e.g. \"D5\") or add an entry to "
            f"BOARD_BUTTON_PINS.",
        )
    pin = getattr(board, pin_name, None)
    if pin is None:
        raise RuntimeError(
            f"board has no pin named {pin_name!r} — check your "
            f"BUTTON_PIN setting / BOARD_BUTTON_PINS mapping.",
        )
    return pin


# --- Button setup (active-low with internal pull-up) ---
button = digitalio.DigitalInOut(_resolve_button_pin())
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

# --- LED setup ---
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# --- Debounce state ---
last_stable = button.value
last_change_ms = ticks_ms()

print("Button debounce — press button to flip the LED.\n")

while True:
    now = ticks_ms()
    raw = button.value  # False when pressed (active-low)

    if raw != last_stable and ticks_diff(now, last_change_ms) >= DEBOUNCE_MS:
        last_stable = raw
        last_change_ms = now

        if not raw:  # button just pressed
            led.value = not led.value
            print(f"  [{now:>5} ms] press → toggle")
