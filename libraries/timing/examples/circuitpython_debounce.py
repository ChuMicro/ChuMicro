"""Button debounce — CircuitPython.

Reads a physical button with software debounce using ``ticks_ms``
and ``ticks_diff``.  Toggles the onboard LED on each accepted press.

Setup:
1. Install ``chumicro_timing`` (``circup install chumicro-timing``
   or copy the package to ``lib/``).
2. Uses ``board.BUTTON`` — the built-in user button on many boards
   (Feather, QT Py, Metro, etc.).  If your board lacks a built-in
   button, wire one between any GPIO and **GND** and change the pin
   (e.g., ``board.D5``).  The internal pull-up is enabled.
3. Save this file as ``code.py`` on the board.

Runs on CircuitPython.
"""

import board
import digitalio
from chumicro_timing import ticks_diff, ticks_ms

DEBOUNCE_MS = 20

# --- Button setup (active-low with internal pull-up) ---
# Set BUTTON_PIN to your pin name (e.g. "D5", "GP14") to skip autodetect.
BUTTON_PIN = ""

if BUTTON_PIN:
    button_pin = getattr(board, BUTTON_PIN)
else:
    for name in ("D5", "GP14", "IO5", "BUTTON"):
        button_pin = getattr(board, name, None)
        if button_pin is not None:
            print(f"button on board.{name}")
            break
    else:
        raise RuntimeError(
            "No input pin matched — set BUTTON_PIN at the top of "
            "this file to a name from `dir(board)`.",
        )
button = digitalio.DigitalInOut(button_pin)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

# --- LED setup ---
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# --- Debounce state ---
last_stable = button.value
last_change_ms = ticks_ms()

while True:
    now = ticks_ms()
    raw = button.value  # False when pressed (active-low)

    if raw != last_stable and ticks_diff(now, last_change_ms) >= DEBOUNCE_MS:
        last_stable = raw
        last_change_ms = now

        if not raw:  # button just pressed
            led.value = not led.value
