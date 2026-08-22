"""A button that flips the onboard LED, on CircuitPython.

Reads a physical button and toggles the LED on every press.  A long press
turns the LED off and prints how long it was held, so you can feel the
difference between a tap and a hold without any extra wiring.

Setup:
1. Install ``chumicro_buttons`` (``circup install chumicro_buttons``).
2. Wire a momentary button between the chosen GPIO and **GND**.  The internal
   pull-up is switched on for you, so no extra parts are needed.  Many boards
   (Feather, QT Py, Metro) expose a built-in button as ``board.BUTTON``.
3. Save this file as ``code.py`` on the board.

Example output::

    Press to toggle the LED.  Hold to turn it off.

      [  815 ms] press -> LED on
      [ 1407 ms] press -> LED off
      [ 2260 ms] held 500 ms -> LED off

Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_button_toggle.py`` for the MP equivalent.
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks_ms

# Set BUTTON_PIN to the pin attribute on the `board` module
# (e.g. "D5", "GP14", "BUTTON") for your wiring.
BUTTON_PIN = "GP14"

button = Button(pin=getattr(board, BUTTON_PIN), long_press_ms=500)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

print("Press to toggle the LED.  Hold to turn it off.\n")

while True:
    now = ticks_ms()
    button.check(now)

    if button.just_pressed:
        led.value = not led.value
        print(f"  [{now:5d} ms] press -> LED {'on' if led.value else 'off'}")

    if button.just_long_pressed:
        led.value = False
        print(f"  [{now:5d} ms] held {button.held_ms} ms -> LED off")

    # Everything else your device does goes here, one small step at a time.
