"""Toggle the onboard LED with a button, debounced by hand, on MicroPython.

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
ESP32 board, set ``BUTTON_PIN`` to 0 and press the BOOT button, which needs no
wiring, and set ``LED_PIN`` to the onboard LED's GPIO number: 15 on a Lolin S2
Mini, 2 on most ESP32 dev boards.

Example output::

    Press the button to flip the LED.

      press, LED on
      press, LED off
      press, LED on
      ...

Setup:
1. Install the library:
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing``.
2. Copy this file to the board as ``main.py``.

Runs on MicroPython.
"""

# ChuMicro's example tools read this line: this file needs MicroPython.
__chumicro_runtimes__ = ("micropython",)

from chumicro_timing import ticks_diff, ticks_ms
from machine import Pin

BUTTON_PIN = 14     # GP14 on a Pi Pico W.  0 is the BOOT button on most ESP32 boards.
LED_PIN = "LED"     # Pi Pico W.  15 on a Lolin S2 Mini, 2 on most ESP32 dev boards.

DEBOUNCE_MS = 20

# The button reads 1 while released and 0 while pressed, because the pull-up
# holds the pin high until the button connects it to GND.
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

led = Pin(LED_PIN, Pin.OUT)

# The last level the debouncer accepted, and when it accepted it.
accepted_level = button.value()
last_change_ms = ticks_ms()

print("Press the button to flip the LED.\n")

while True:
    now = ticks_ms()
    level = button.value()

    # A change counts only when it comes DEBOUNCE_MS or more after the last
    # accepted one.  Anything sooner is the contacts bouncing.
    if level != accepted_level and ticks_diff(now, last_change_ms) >= DEBOUNCE_MS:
        accepted_level = level
        last_change_ms = now

        if not level:   # 0 means pressed
            led.value(not led.value())
            print("  press, LED on" if led.value() else "  press, LED off")

    # Nothing above waits, so code you add here runs on every pass.
