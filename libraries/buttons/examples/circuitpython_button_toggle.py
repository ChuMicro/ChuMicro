"""Toggle the onboard LED with a button, on CircuitPython.

Each press flips the onboard LED.  Hold the button for half a second and the
LED turns off, whatever the press did, so you can feel the difference
between a tap and a hold.  The console prints each one.  The library
debounces the button for you, and a tap shorter than one pass of the loop
still counts.

Wiring: a momentary button from GP14 to GND on a Pi Pico W.  The pin's
internal pull-up is switched on for you, so the button is the only part.  On
an ESP32-S2 board, wire it to IO14 and set ``BUTTON_PIN`` to ``board.IO14``,
or use a built-in button with ``board.BUTTON`` where the board has one, such
as the Lolin S2 Mini.

Example output::

    Press to toggle the LED.  Hold to turn it off.

      press, LED on
      press, LED off
      press, LED on
      held 500 ms, LED off

Setup:
1. Install the library: ``circup install chumicro_buttons``.  It brings
   ``chumicro_timing`` along.
2. Save this file as ``code.py`` on the CIRCUITPY drive.

Runs on CircuitPython.
"""

# ChuMicro's example tools read this line: this file needs CircuitPython.
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms

BUTTON_PIN = board.GP14     # board.IO14 on an ESP32-S2, or board.BUTTON for a built-in one

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

# ticks is the clock the button times presses with.  A hold of long_press_ms
# or more counts as a long press.
button = Button(pin=BUTTON_PIN, ticks=ticks, long_press_ms=500)

print("Press to toggle the LED.  Hold to turn it off.\n")

while True:
    now = ticks_ms()

    # Collect whatever the button did since the last pass.  Never waits.
    button.check(now)

    # True on exactly one pass per press.
    if button.just_pressed:
        led.value = not led.value
        print("  press, LED on" if led.value else "  press, LED off")

    # True on exactly one pass, once a press has lasted long_press_ms.
    if button.just_long_pressed:
        led.value = False
        print(f"  held {button.held_ms} ms, LED off")

    # Nothing above waits, so code you add here runs on every pass.
