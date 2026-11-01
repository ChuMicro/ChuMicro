"""Toggle the onboard LED with a button, on MicroPython.

Each press flips the onboard LED.  Hold the button for half a second and the
LED turns off, whatever the press did, so you can feel the difference
between a tap and a hold.  The console prints each one.  The library
debounces the button for you and installs the pin interrupt that catches a
tap shorter than one pass of the loop.

Wiring: a momentary button from GP14 to GND on a Pi Pico W.  The pin's
internal pull-up is switched on for you, so the button is the only part.  On
an ESP32 board, set ``BUTTON_PIN`` to 0 and press the BOOT button, which needs
no wiring, and set ``LED_PIN`` to the onboard LED's GPIO number: 15 on a Lolin
S2 Mini, 2 on most ESP32 dev boards.

Example output::

    Press to toggle the LED.  Hold to turn it off.

      press, LED on
      press, LED off
      press, LED on
      held 500 ms, LED off

Setup:
1. Install the library:
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_buttons``.
   It brings ``chumicro_timing`` along.
2. Copy this file to the board as ``main.py``.

Runs on MicroPython.
"""

# ChuMicro's example tools read this line: this file needs MicroPython.
__chumicro_runtimes__ = ("micropython",)

from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms
from machine import Pin

BUTTON_PIN = 14     # GP14 on a Pi Pico W.  0 is the BOOT button on most ESP32 boards.
LED_PIN = "LED"     # Pi Pico W.  15 on a Lolin S2 Mini, 2 on most ESP32 dev boards.

led = Pin(LED_PIN, Pin.OUT)

# ticks is the clock the button times presses with.  A hold of long_press_ms
# or more counts as a long press.
button = Button(pin=Pin(BUTTON_PIN), ticks=ticks, long_press_ms=500)

print("Press to toggle the LED.  Hold to turn it off.\n")

while True:
    now = ticks_ms()

    # Collect whatever the button did since the last pass.  Never waits.
    button.check(now)

    # True on exactly one pass per press.
    if button.just_pressed:
        led.value(not led.value())
        print("  press, LED on" if led.value() else "  press, LED off")

    # True on exactly one pass, once a press has lasted long_press_ms.
    if button.just_long_pressed:
        led.value(0)
        print(f"  held {button.held_ms} ms, LED off")

    # Nothing above waits, so code you add here runs on every pass.
