"""Runner LED blink: MicroPython.

Toggles the onboard LED every 500 ms using a periodic runner task.
Prints a line on each toggle so a serial console (or a sweep harness)
can verify the loop is alive without watching the LED itself.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``mpremote mip install chumicro-runner`` or copy both
   packages to the board).
2. No extra wiring needed.  Uses pin 2, the built-in LED on most
   ESP32 dev boards.  Change ``Pin(2)`` to match your board.
3. Save this file as ``main.py`` on the board.

Example output::

    Running LED blink (toggle every 500 ms)...

      blink!
      blink!
      ...

Runs on MicroPython.
"""

#: MicroPython-only.  Uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_blink.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_runner import Runner
from machine import Pin

# Set up the onboard LED.  Pin 2 is the built-in LED on most
# ESP32 boards.  Adjust the pin number for your hardware.
led = Pin(2, Pin.OUT)


def toggle_led(now_ms: int) -> None:
    """Toggle the LED state and print a marker line.

    Args:
        now_ms: Current tick value.
    """
    led.value(not led.value())
    print("  blink!")


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)

print("Running LED blink (toggle every 500 ms)...\n")

while True:
    runner.tick()
