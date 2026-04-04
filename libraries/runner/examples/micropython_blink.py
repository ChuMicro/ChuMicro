# requires: hardware
"""Runner LED blink — MicroPython.

Toggles the onboard LED every 500 ms using a periodic runner task.
Drop this file onto your board as ``main.py``.

Wiring: none — uses pin 2, which is the built-in LED on most
ESP32 dev boards.  Change ``Pin(2)`` to match your board.

Runs on MicroPython.
"""

from chumicro_runner import Runner
from machine import Pin

# Set up the onboard LED.  Pin 2 is the built-in LED on most
# ESP32 boards.  Adjust the pin number for your hardware.
led = Pin(2, Pin.OUT)


def toggle_led(now_ms):
    """Toggle the LED state."""
    led.value(not led.value())


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)

while True:
    runner.tick()

