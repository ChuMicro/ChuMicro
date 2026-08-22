"""A button that flips the onboard LED, on MicroPython.

Reads a physical button and toggles the LED on every press.  A long press
turns the LED off and prints how long it was held, so you can feel the
difference between a tap and a hold without any extra wiring.

The library installs the capture interrupt for you.  A tap that starts and
ends between two passes of this loop still registers, which is the part that
is easy to get wrong by hand.

Setup:
1. Install ``chumicro_buttons``
   (``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_buttons``).
2. Wire a momentary button between the chosen GPIO and **GND**.  The internal
   pull-up is switched on for you, so no extra parts are needed.
3. Copy this file to the board as ``main.py``.

Example output::

    Press to toggle the LED.  Hold to turn it off.

      [  815 ms] press -> LED on
      [ 1407 ms] press -> LED off
      [ 2260 ms] held 500 ms -> LED off

Runs on MicroPython.
"""

#: MicroPython-only.  Uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_button_toggle.py`` for the CP equivalent.
__chumicro_runtimes__ = ("micropython",)

from chumicro_buttons import Button
from chumicro_timing import ticks, ticks_ms
from machine import Pin

# Set BUTTON_PIN to the GPIO number your button is wired to.
BUTTON_PIN = 14

# Most boards expose the onboard LED as "LED"; some want a GPIO number here.
led = Pin("LED", Pin.OUT)

button = Button(pin=Pin(BUTTON_PIN), ticks=ticks, long_press_ms=500)

print("Press to toggle the LED.  Hold to turn it off.\n")

while True:
    now = ticks_ms()
    button.check(now)

    if button.just_pressed:
        led.value(not led.value())
        print(f"  [{now:5d} ms] press -> LED {'on' if led.value() else 'off'}")

    if button.just_long_pressed:
        led.value(0)
        print(f"  [{now:5d} ms] held {button.held_ms} ms -> LED off")

    # Everything else your device does goes here, one small step at a time.
