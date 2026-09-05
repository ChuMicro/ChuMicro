"""Blink an LED from one file that runs unchanged on both device runtimes.

Wiring: an LED and its resistor from GPIO15 to ground.  A LOLIN S2 Mini
already has its onboard LED there, so nothing needs wiring; on a Pi Pico W
GPIO15 is the header pin marked GP15.  The number is the same on both
runtimes because ``digital_output`` resolves it to ``machine.Pin`` or
``digitalio.DigitalInOut`` for the runtime it finds itself on.

Example output::

    led on
    led off
"""
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_compat.wiring import digital_output
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

led = digital_output(15, value=0)

lit = 0
next_toggle_ms = ticks_ms()
while True:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, next_toggle_ms) >= 0:
        next_toggle_ms = ticks_add(now_ms, 500)
        lit = 1 - lit
        led(lit)
        print("led on" if lit else "led off")
