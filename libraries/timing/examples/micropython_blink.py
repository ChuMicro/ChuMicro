"""Heartbeat LED blink — MicroPython.

Toggles the onboard LED once per second using a non-blocking
``Heartbeat`` timer.

Setup:
1. Install ``chumicro_timing`` (``mpremote mip install chumicro-timing``
   or copy the package to the board).
2. No extra wiring — uses pin 2, the built-in LED on most ESP32
   dev boards.  Change ``Pin(2)`` to match your board.
3. Save this file as ``main.py`` on the board.

Runs on MicroPython.
"""

#: MicroPython-only — uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_blink.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_timing import Heartbeat, ticks_ms
from machine import Pin

# Set up the onboard LED.  Pin 2 is the built-in LED on most
# ESP32 boards.  Adjust the pin number for your hardware.
led = Pin(2, Pin.OUT)

# Create a heartbeat that fires once per second.
heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()

    # poll() returns True once per period, then resets.
    if heartbeat.poll(now):
        led.value(not led.value())
