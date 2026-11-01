"""Debounce a pretend button by hand, printing what it accepts and what it ignores.

A button's metal contacts bounce for a few milliseconds when they meet or
part, so one press reads as on-off-on.  This loop accepts a change only when
at least 20 ms have passed since the last change it accepted, measured with
``ticks_diff``, and ignores the bounces in between.  The pretend button
presses and releases twice a second, bouncing every time, and the console
shows each accepted press and release next to the bounces it threw away.

Arduino's Debounce sketch waits for the pin to hold still for
``debounceDelay`` before believing it.  This loop believes the first change at
once and then ignores the pin for ``DEBOUNCE_MS``, so a press shows up sooner.
``chumicro_buttons`` does all of this for you, along with long presses and
double clicks.  ``circuitpython_debounce.py`` and ``micropython_debounce.py``
run the same loop on a real button.

Example output::

    Debouncing a pretend button with a 20 ms quiet period.

      [  123 ms] PRESS accepted
      [  204 ms] RELEASE accepted
      [  623 ms] PRESS accepted
      [  628 ms]   bounce ignored, 5 ms after the last change
      [  702 ms] RELEASE accepted
      [  708 ms]   bounce ignored, 6 ms after the last change
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_diff, ticks_ms

DEBOUNCE_MS = 20

# The pretend button, as (how long in ms, pressed or not) in order.  It is a
# press with two bounces, a hold, then a release with two bounces, repeating.
BUTTON_SIGNAL = (
    (120, False),   # not pressed
    (5, True),      # contacts meet
    (5, False),     # bounce
    (5, True),      # bounce
    (65, True),     # held down
    (5, False),     # contacts part
    (5, True),      # bounce
    (5, False),     # bounce
    (285, False),   # not pressed, then the pattern repeats
)
SIGNAL_LENGTH_MS = sum(duration_ms for duration_ms, _ in BUTTON_SIGNAL)

started_ms = ticks_ms()


def read_button(now_ms: int) -> bool:
    """Return True while the pretend button reads as pressed.

    On a board this is a pin read, such as ``return not button_pin.value``
    for a button wired to ground.
    """
    position_ms = ticks_diff(now_ms, started_ms) % SIGNAL_LENGTH_MS
    for duration_ms, pressed in BUTTON_SIGNAL:
        if position_ms < duration_ms:
            return pressed
        position_ms -= duration_ms
    return False


# The last state the debouncer accepted, and when it accepted it.
accepted_pressed = False
last_change_ms = started_ms

print(f"Debouncing a pretend button with a {DEBOUNCE_MS} ms quiet period.\n")

while True:
    now = ticks_ms()
    pressed = read_button(now)

    if pressed != accepted_pressed:
        since_last_change_ms = ticks_diff(now, last_change_ms)
        elapsed_ms = ticks_diff(now, started_ms)

        if since_last_change_ms >= DEBOUNCE_MS:
            # Quiet for long enough: this is a real press or release.
            accepted_pressed = pressed
            last_change_ms = now
            action = "PRESS" if pressed else "RELEASE"
            print(f"  [{elapsed_ms:5d} ms] {action} accepted")
        else:
            # Too soon after the last accepted change: a bounce.
            print(f"  [{elapsed_ms:5d} ms]   bounce ignored, "
                  f"{since_last_change_ms} ms after the last change")

    # Check every 5 ms, so the console shows each bounce once instead of once
    # per pass.  A real program spends this time on its other work.
    time.sleep(0.005)
