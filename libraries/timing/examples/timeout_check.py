"""Give up on a slow sensor after half a second, without pausing the loop.

Once a second the program starts asking a pretend sensor whether it has a
reading.  A ``Deadline`` set for 500 ms decides when to stop asking: some
attempts get an answer in time and print how long it took, and the slow ones
print a timeout.  The loop checks the sensor and the deadline on every pass
and never waits for either.

``Rate`` starts the attempts and ``Deadline`` ends them, which is the usual
pairing: a ``Rate`` comes due again and again, and a ``Deadline`` expires once
until you ``reset()`` it.

Example output::

    Asking the sensor once a second, giving up after 500 ms.

      attempt 1: ready after 300 ms
      attempt 2: no answer in 500 ms, giving up
      attempt 3: ready after 150 ms
      attempt 4: no answer in 500 ms, giving up
      attempt 5: ready after 450 ms
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_timing import Deadline, Rate, ticks_diff, ticks_ms

TIMEOUT_MS = 500

# How long the pretend sensor takes to answer on each attempt, in turn.
# 900 is slower than the timeout, so those attempts give up.
ANSWER_AFTER_MS = (300, 900, 150, 900, 450)

attempt = 0
attempt_started_ms = ticks_ms()
waiting = False


def sensor_is_ready(now_ms: int) -> bool:
    """Return True once this attempt has waited as long as the pretend sensor takes.

    On a board this is one quick read of a pin or a status register, such as
    ``return ready_pin.value``.
    """
    answer_after_ms = ANSWER_AFTER_MS[(attempt - 1) % len(ANSWER_AFTER_MS)]
    return ticks_diff(now_ms, attempt_started_ms) >= answer_after_ms


# A new attempt comes due once a second.
next_attempt = Rate(1000, ticks_ms())

# Expires TIMEOUT_MS after it is set.  Each attempt sets it again with reset().
give_up = Deadline(TIMEOUT_MS, ticks_ms())

print(f"Asking the sensor once a second, giving up after {TIMEOUT_MS} ms.\n")

while True:
    now = ticks_ms()

    # Once a second, start a new attempt and give it TIMEOUT_MS from now.
    if next_attempt.due(now):
        attempt += 1
        attempt_started_ms = now
        give_up.reset(now)
        waiting = True

    if waiting and sensor_is_ready(now):
        waited_ms = ticks_diff(now, attempt_started_ms)
        print(f"  attempt {attempt}: ready after {waited_ms} ms")
        waiting = False

    if waiting and give_up.expired(now):
        print(f"  attempt {attempt}: no answer in {TIMEOUT_MS} ms, giving up")
        waiting = False

    # Nothing above waits, so code you add here runs on every pass.
