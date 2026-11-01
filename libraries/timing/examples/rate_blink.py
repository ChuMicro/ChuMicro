"""Blink a pretend LED once a second without ever pausing the loop.

The console prints ``LED on`` and ``LED off`` in turn, one line a second,
forever.  Nothing in the loop waits: ``Rate`` answers "has a second passed
yet?" on every pass and says yes once per second.  That leaves the loop free
for whatever else you add, which ``time.sleep(1)`` would not.

If you know Arduino, this is BlinkWithoutDelay: ``ticks_ms()`` plays the part
of ``millis()``, and ``Rate`` keeps the ``previousMillis`` bookkeeping for you.
To blink a real LED, run ``circuitpython_blink.py`` or ``micropython_blink.py``.

Example output::

    Blinking a pretend LED once a second.

      LED on
      LED off
      LED on
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_timing import Rate, ticks_ms

# A timer that comes due every 1000 ms, counting from now.
every_second = Rate(1000, ticks_ms())

led_on = False

print("Blinking a pretend LED once a second.\n")

while True:
    # Read the clock once per pass and use that one reading below.
    now = ticks_ms()

    # due() is True once each time a second has passed, and False otherwise.
    if every_second.due(now):
        led_on = not led_on
        print("  LED on" if led_on else "  LED off")

    # Nothing above waits, so code you add here runs on every pass.
