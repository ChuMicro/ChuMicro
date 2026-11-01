"""Blink the board's LED every half second with one timed job.

The built-in LED turns on and off every 500 ms, forever.  The serial console
prints ``LED on`` or ``LED off`` with each change, so you can watch the loop
run without looking at the board.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``
   (``circup install chumicro_runner``, or copy both packages into ``lib/``).
2. No wiring: the example uses the built-in LED, ``board.LED``.
3. Save this file as ``code.py`` on the board.

Example output::

    Blinking the LED every 500 ms...
    LED on
    LED off
    LED on
    LED off
    ...

Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` + ``digitalio`` (CP API).
#: Pair: ``micropython_blink.py`` for the MP equivalent (``machine.Pin``).
__chumicro_runtimes__ = ("circuitpython",)

import board
import digitalio
from chumicro_runner import Runner

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT


def toggle_led(now_ms: int) -> None:
    """Flip the LED and print its new state.

    The runner passes every job ``now_ms``, the time of the current tick in
    milliseconds.  This job has no use for it.
    """
    led.value = not led.value
    print("LED on" if led.value else "LED off")


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)   # call toggle_led every 500 ms

print("Blinking the LED every 500 ms...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
