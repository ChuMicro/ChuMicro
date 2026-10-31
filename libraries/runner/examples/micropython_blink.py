"""Blink the board's LED every half second with one timed job.

The built-in LED turns on and off every 500 ms, forever.  The serial console
prints ``LED on`` or ``LED off`` with each change, so you can watch the loop
run without looking at the board.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing`` on the board
   (``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner``,
   or copy both packages into ``lib/``).
2. No wiring: pin 2 is the built-in LED on most ESP32 dev boards.  On a
   Pico W, set ``LED_PIN = "LED"``.
3. Save this file as ``main.py`` on the board.

Example output::

    Blinking the LED every 500 ms...
    LED on
    LED off
    LED on
    LED off
    ...

Runs on MicroPython.
"""

#: MicroPython-only.  Uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_blink.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_runner import Runner
from machine import Pin

LED_PIN = 2   # change to match your board's LED

led = Pin(LED_PIN, Pin.OUT)


def toggle_led(now_ms: int) -> None:
    """Flip the LED and print its new state.

    The runner passes every job ``now_ms``, the time of the current tick in
    milliseconds.  This job has no use for it.
    """
    led.value(not led.value())
    print("LED on" if led.value() else "LED off")


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)   # call toggle_led every 500 ms

print("Blinking the LED every 500 ms...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
