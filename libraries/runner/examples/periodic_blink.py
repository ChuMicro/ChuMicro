"""Blink a pretend LED every half second with one timed job.

The program prints ``LED on`` and ``LED off`` in turn every 500 ms, forever.
It is the ``time.sleep()`` blink from a first board tutorial with the sleep
taken out: ``add_periodic`` asks the runner to call ``toggle_led`` every
500 ms, ``runner.tick()`` makes that call when it is due, and
``runner.wait()`` idles the CPU until the next one.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python periodic_blink.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.

Example output::

    Blinking every 500 ms...
    LED on
    LED off
    LED on
    LED off
    ...

To blink a real LED, ``circuitpython_blink.py`` and ``micropython_blink.py``
add the pin setup to this same program.

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner

led_on = False


def toggle_led(now_ms: int) -> None:
    """Flip the pretend LED and print its new state.

    The runner passes every job ``now_ms``, the time of the current tick in
    milliseconds.  This job has no use for it.
    """
    global led_on
    led_on = not led_on
    print("LED on" if led_on else "LED off")


runner = Runner()
runner.add_periodic(toggle_led, period_ms=500)   # call toggle_led every 500 ms

print("Blinking every 500 ms...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
