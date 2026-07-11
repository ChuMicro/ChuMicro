"""Runner LED blink: CircuitPython.

Toggles the onboard LED every 500 ms using a periodic runner task.
Prints a line on each toggle so a serial console (or a sweep harness)
can verify the loop is alive without watching the LED itself.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro_runner`` or copy both packages
   to ``lib/``).
2. No extra wiring needed.  Uses the built-in LED (``board.LED``).
3. Save this file as ``code.py`` on the board.

Example output::

    Running LED blink (toggle every 500 ms)...

      blink!
      blink!
      ...

Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_blink.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_runner import Runner

# Set up the onboard LED as a digital output.
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def toggle_led(now_ms: int) -> None:
    """Toggle the LED state and print a marker line.

    Args:
        now_ms: Current tick value.
    """
    led.value = not led.value
    print("  blink!")


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)

print("Running LED blink (toggle every 500 ms)...\n")

while True:
    runner.tick()
