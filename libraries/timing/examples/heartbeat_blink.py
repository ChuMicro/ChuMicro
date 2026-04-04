"""Heartbeat blink — the embedded hello world.

Prints a message once per second using a non-blocking heartbeat timer.
On a real board, replace the ``print`` with an LED toggle
(``led.value = not led.value``).

Example output::

    Running heartbeat blink...

      beat!
      beat!
      beat!
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Heartbeat, ticks_ms

# Create a heartbeat that fires once per second.
heartbeat = Heartbeat(period_ms=1000)

print("Running heartbeat blink...\n")

while True:
    # Capture the current time once and pass it to all timing checks.
    # This ensures consistent behavior even if the checks take time
    # to execute.
    now = ticks_ms()

    # poll() returns True once per period and advances the timer.
    # It returns False on every other call.
    if heartbeat.poll(now):
        # On a real board: led.value = not led.value
        print("  beat!")

    # In a real project, the rest of your main loop goes here —
    # reading sensors, checking buttons, updating displays, etc.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.01)
