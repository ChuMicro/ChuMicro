"""Every button event on a laptop, with no board attached.

Drives a ``Button`` from ``FakeButtonSource``, the same hand-driven source the
library's own tests use.  Each edge carries the time it happened, so this runs
the identical code path a real board takes and you can watch a press, a long
press, auto-repeat, and a double click resolve in order.

This is how you write button logic before the hardware arrives, and how you
keep testing it afterwards without wearing out a switch.

Example output::

    Simulated button events...

      [ 100 ms] press
      [ 600 ms] long press (held 500 ms)
      [ 800 ms] repeat
      [1000 ms] repeat
      [1100 ms] release
      [1360 ms] click series of 1

Runs on CPython.
"""

#: CPython-only.  Uses the test-support fake in place of real pins.
#: Pair: ``circuitpython_button_toggle.py`` / ``micropython_button_toggle.py``
#: for the same button on real hardware.
__chumicro_runtimes__ = ("cpython",)

from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource

source = FakeButtonSource()
button = Button(
    source=source,
    long_press_ms=500,     # a hold this long counts as a long press
    repeat_ms=200,         # then repeat every 200 ms while still held
    repeat_delay_ms=700,   # starting 700 ms after the press
    click_ms=250,          # a click series closes after 250 ms of quiet
)

# The script the fake source plays back: what happened, and when.
PRESSED_AT_MS = 100
RELEASED_AT_MS = 1100
LAST_TICK_MS = 1500
TICK_STEP_MS = 20

print("Simulated button events...\n")

now_ms = 0
while now_ms <= LAST_TICK_MS:
    # Hand the fake the edges a person would have produced by this point.
    if now_ms == PRESSED_AT_MS:
        source.press(at_ms=PRESSED_AT_MS)
    if now_ms == RELEASED_AT_MS:
        source.release(at_ms=RELEASED_AT_MS)

    button.check(now_ms)

    if button.just_pressed:
        print(f"  [{now_ms:4d} ms] press")
    if button.just_long_pressed:
        print(f"  [{now_ms:4d} ms] long press (held {button.held_ms} ms)")
    if button.just_repeated:
        print(f"  [{now_ms:4d} ms] repeat")
    if button.just_released:
        print(f"  [{now_ms:4d} ms] release")
    if button.just_clicked:
        print(f"  [{now_ms:4d} ms] click series of {button.click_count}")

    now_ms += TICK_STEP_MS
