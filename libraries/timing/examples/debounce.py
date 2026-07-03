"""Button debounce using tick functions directly.

Demonstrates ``ticks_ms`` and ``ticks_diff`` for ignoring rapid state
changes.  This is the classic debounce pattern.  A raw button signal bounces
for a few milliseconds after each press.  The debouncer records the
timestamp of the last accepted transition and ignores any further
changes until the quiet period has elapsed.

On a real board, replace ``read_raw_button()`` with a GPIO read.

Example output::

    Debounce demo (20 ms quiet period)...

      [ 1121 ms] raw=True  -> PRESS accepted
      [ 1128 ms] raw=False    (ignored, 7 ms < 20 ms)
      [ 1202 ms] raw=False -> RELEASE accepted
      [ 1209 ms] raw=True     (ignored, 7 ms < 20 ms)
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import ticks_diff, ticks_ms

DEBOUNCE_MS = 20

# --- Simulated raw button signal ---
# Each entry is (duration_ms, pin_state).  The pattern fakes a noisy
# press (True with bounces) followed by a clean idle (False).
_SIGNAL = [
    (120, False),   # idle
    (5, True),      # press edge
    (5, False),     # bounce
    (5, True),      # bounce
    (65, True),     # held
    (5, False),     # release edge
    (5, True),      # bounce
    (5, False),     # bounce
    (285, False),   # idle until cycle repeats
]
_CYCLE_MS = sum(duration for duration, _ in _SIGNAL)
_start = ticks_ms()


def read_raw_button() -> bool:
    """Return the simulated raw button state.

    Returns:
        True if the button is pressed.

    On a real board::

        return not button_pin.value   # active-low button
    """
    offset = ticks_diff(ticks_ms(), _start) % _CYCLE_MS
    elapsed = 0
    for duration, state in _SIGNAL:
        elapsed += duration
        if offset < elapsed:
            return state
    return False


# --- Debounce state ---
last_stable = False
last_change_ms = ticks_ms()

print(f"Debounce demo ({DEBOUNCE_MS} ms quiet period)...\n")

while True:
    now = ticks_ms()
    raw = read_raw_button()
    elapsed_since_change = ticks_diff(now, last_change_ms)
    elapsed_total = ticks_diff(now, _start)

    if raw != last_stable:
        if elapsed_since_change >= DEBOUNCE_MS:
            # Enough quiet time has passed, so accept the transition.
            action = "PRESS" if raw else "RELEASE"
            print(f"  [{elapsed_total:5d} ms] raw={raw!s:<6s}"
                  f"-> {action} accepted")
            last_stable = raw
            last_change_ms = now
        else:
            # Too soon after the last transition: bounce, ignore.
            print(f"  [{elapsed_total:5d} ms] raw={raw!s:<6s}"
                  f"   (ignored, {elapsed_since_change} ms "
                  f"< {DEBOUNCE_MS} ms)")

    # In a real project, the rest of your main loop goes here.
    time.sleep(0.005)
