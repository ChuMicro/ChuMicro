"""Button debounce — MicroPython.

Reads a physical button with software debounce using ``ticks_ms``
and ``ticks_diff``.  Toggles the onboard LED on each accepted press.

Setup:
1. Install ``chumicro_timing`` (``mpremote mip install chumicro-timing``
   or copy the package to the board).
2. Wire a momentary button between **GPIO0** and **GND**.
   The internal pull-up is enabled, so no external resistor is needed.
   Change ``Pin(0)`` to match your wiring.
3. Save this file as ``main.py`` on the board.

Runs on MicroPython.
"""

#: MicroPython-only — uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_debounce.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_timing import ticks_diff, ticks_ms
from machine import Pin

DEBOUNCE_MS = 20

# --- Button setup (active-low with internal pull-up) ---
button = Pin(0, Pin.IN, Pin.PULL_UP)

# --- LED setup (pin 2 is the built-in LED on most ESP32 boards) ---
led = Pin(2, Pin.OUT)

# --- Debounce state ---
last_stable = button.value()
last_change_ms = ticks_ms()
led_state = False

while True:
    now = ticks_ms()
    raw = button.value()  # 0 when pressed (active-low)

    if raw != last_stable and ticks_diff(now, last_change_ms) >= DEBOUNCE_MS:
        last_stable = raw
        last_change_ms = now

        if not raw:  # button just pressed
            led_state = not led_state
            led.value(led_state)
