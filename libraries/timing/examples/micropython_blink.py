"""Periodic LED blink — MicroPython.

Toggles the onboard LED once per second using a non-blocking
``Rate`` timer (drift-free, phase-aligned cadence).  Prints a line
on each toggle so a serial console (or a sweep harness) can verify
the loop without watching the LED itself.

Setup:
1. Install ``chumicro_timing``
   (``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing``
   or copy the package to the board).
2. No extra wiring — uses pin 2, the built-in LED on most ESP32
   dev boards.  Change ``Pin(2)`` to match your board.
3. Save this file as ``main.py`` on the board.

Example output::

    Running LED blink (1 Hz)...

      blink!
      blink!
      ...

Runs on MicroPython.
"""

#: MicroPython-only — uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_blink.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_timing import Rate, ticks_ms
from machine import Pin

# Set up the onboard LED.  Pin 2 is the built-in LED on most
# ESP32 boards.  Adjust the pin number for your hardware.
led = Pin(2, Pin.OUT)

# Create a drift-free cadence that fires once per second.
beat = Rate(1000, ticks_ms())

print("Running LED blink (1 Hz)...\n")

while True:
    now = ticks_ms()

    # due() returns True at most once per period, staying phase-aligned.
    if beat.due(now):
        led.value(not led.value())
        print("  blink!")
