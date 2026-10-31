"""Fill in some of a function's arguments now and the rest later, with ``partial``.

``partial(set_led, 13)`` returns a new function that already knows the pin
number, so you call it with only the brightness.  This example makes one
such function per LED, then fades both pretend LEDs up and down forever,
printing every step, so you can watch it in the serial console with no
wiring.

It also shows the other two things ``partial`` is good for: you can freeze
a keyword argument and still replace it in a single call, and the functions
it makes are ordinary callbacks you can keep in a list and call later, the
way a button handler or a scheduler would.

Setup:

1. Install the library.  On CircuitPython run
   ``circup install chumicro_compat``; on MicroPython run
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat``.
2. No wiring needed.
3. Save this file as ``code.py`` (CircuitPython) or ``main.py``
   (MicroPython) on the board.

Example output::

    status LED on pin 13: 100%
    warning LED on pin 13: 100%
    status LED on pin 13: 0%
    power LED on pin 2: 0%
    status LED on pin 13: 25%
    power LED on pin 2: 25%

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_compat.functools import partial


def set_led(pin, brightness, label="LED"):
    """Pretend to set the LED on *pin*: print its label and brightness."""
    print(f"{label} on pin {pin}: {brightness}%")


# partial() fills in the arguments you give it now.  From here on,
# set_status_led(50) runs set_led(13, 50, label="status LED").
set_status_led = partial(set_led, 13, label="status LED")
set_power_led = partial(set_led, 2, label="power LED")

# A keyword frozen by partial() can still be replaced in one call.
set_status_led(100)
set_status_led(100, label="warning LED")

# The new functions are ordinary callbacks: keep them in a list and
# call each one in turn.
leds = [set_status_led, set_power_led]

# Fade both LEDs between 0% and 100% in steps of 25, forever.
brightness = 0
step = 25
while True:
    for set_brightness in leds:
        set_brightness(brightness)

    brightness += step
    if brightness == 0 or brightness == 100:
        step = -step

    time.sleep(0.5)
