"""Toggle the onboard LED with a button, debounced by hand, on CircuitPython.

Each press of the button flips the onboard LED and prints a line.  A button's
metal contacts bounce for a few milliseconds when they meet, and without
debouncing one press reads as several.  This loop accepts a change only when
at least 20 ms have passed since the last change it accepted, measured with
``ticks_diff``, and ignores the bounces in between.

This file shows how debouncing works.  ``chumicro_buttons`` does it for you,
and also catches a tap that is over before your loop gets round to reading
the pin.

Wiring: a momentary button from GP14 to GND on a Pi Pico W.  The pin's
internal pull-up is switched on below, so the button is the only part.  On an
ESP32-S2 board, wire it to IO14 and change ``board.GP14`` to ``board.IO14``,
or use a built-in button with ``board.BUTTON`` where the board has one, such
as the Lolin S2 Mini.

Example output::

    Press the button to flip the LED.

      press, LED on
      press, LED off
      press, LED on
      ...

Setup:
1. Install the library: ``circup install chumicro_timing``.
2. Save this file as ``code.py`` on the CIRCUITPY drive.

Runs on CircuitPython.
"""

# ChuMicro's example tools read this line: this file needs CircuitPython.
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_timing import ticks_diff, ticks_ms

DEBOUNCE_MS = 20

# The button reads True while released and False while pressed, because the
# pull-up holds the pin high until the button connects it to GND.
button = digitalio.DigitalInOut(board.GP14)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# The last level the debouncer accepted, and when it accepted it.
accepted_level = button.value
last_change_ms = ticks_ms()

print("Press the button to flip the LED.\n")

while True:
    now = ticks_ms()
    level = button.value

    # A change counts only when it comes DEBOUNCE_MS or more after the last
    # accepted one.  Anything sooner is the contacts bouncing.
    if level != accepted_level and ticks_diff(now, last_change_ms) >= DEBOUNCE_MS:
        accepted_level = level
        last_change_ms = now

        if not level:   # False means pressed
            led.value = not led.value
            print("  press, LED on" if led.value else "  press, LED off")

    # Nothing above waits, so code you add here runs on every pass.
