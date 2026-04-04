# requires: hardware
"""Heartbeat LED blink — MicroPython.

Toggles the onboard LED once per second using a non-blocking
``Heartbeat`` timer.

Setup:
1. Copy ``chumicro_timing`` to the board (e.g., via ``mpremote``).
2. Save this file as ``main.py`` on the board.

Wiring: none — uses pin 2, which is the built-in LED on most
ESP32 dev boards.  Change ``Pin(2)`` to match your board.

Runs on MicroPython.
"""

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

