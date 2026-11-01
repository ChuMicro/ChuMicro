"""``ticks_ms``, ``ticks_add``, and ``ticks_diff``: a millisecond clock that stays correct when it rolls over.

A tick is a reading from ``ticks_ms()``, a whole number of milliseconds from 0 to
``TICKS_MAX`` (2**29 - 1).  The count rolls back to 0 about every 6.2 days.  Compare two
ticks with ``ticks_diff`` and offset one with ``ticks_add``.  Plain ``-``, ``+``, and ``<``
give wrong answers across the rollover.
"""

# The wrap constants, the ticks_ms source-resolution order, and the ticks_add /
# ticks_diff math in this module come from Adafruit_CircuitPython_Ticks:
#
#   Copyright (c) 2017 Scott Shawcroft, written for Adafruit Industries
#   Copyright (c) 2021 Jeff Epler for Adafruit Industries
#   Released under the MIT license.
#   https://github.com/adafruit/Adafruit_CircuitPython_Ticks
#
# The same ticks_add / ticks_diff routines are published as a reference
# implementation in CircuitPython's own supervisor.ticks_ms documentation, and
# the OverflowError text matches MicroPython's time.ticks_add.

import time

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# 2**29 matches CircuitPython's ticks_ms wrap; sub-2**30 add/diff keeps
# boards without big-int support from heap-allocating a long.
TICKS_PERIOD = const(1 << 29)
TICKS_MAX = const(TICKS_PERIOD - 1)
TICKS_HALFPERIOD = const(TICKS_PERIOD // 2)


def _resolve_ticks_ms() -> object:
    try:
        import supervisor
    except ImportError:
        supervisor = None
    if supervisor is not None:
        candidate = getattr(supervisor, "ticks_ms", None)
        if callable(candidate):
            return candidate

    candidate = getattr(time, "ticks_ms", None)
    if callable(candidate):
        return candidate

    candidate = getattr(time, "monotonic_ns", None)
    if callable(candidate):
        return lambda: candidate() // 1_000_000

    _monotonic = time.monotonic
    return lambda: int(_monotonic() * 1000)


_raw_ticks_ms = _resolve_ticks_ms()


def ticks_ms() -> int:
    """Return the current tick: milliseconds on the runtime's clock, from 0 to ``TICKS_MAX``.

    Read it once per pass of the loop and hand that one reading to every timer, so every
    timer judges the pass by the same instant.
    """
    return _raw_ticks_ms() & TICKS_MAX


def ticks_add(ticks: int, delta: int) -> int:
    """Return the tick ``delta`` milliseconds after ``ticks``, rolled over into the tick range.

    ``ticks_add(ticks_ms(), 500)`` is the tick half a second from now, the usual way to
    build a deadline.

    Args:
        ticks: A tick from ``ticks_ms()`` or an earlier ``ticks_add``.
        delta: Milliseconds to add.  A negative ``delta`` gives an earlier tick.

    Returns:
        The new tick, from 0 to ``TICKS_MAX``.

    Raises:
        OverflowError: ``delta`` is 2**28 ms (about 3.1 days) or more in either direction.
    """
    if -TICKS_HALFPERIOD < delta < TICKS_HALFPERIOD:
        return (ticks + delta) % TICKS_PERIOD
    raise OverflowError("ticks interval overflow")


def ticks_diff(end: int, start: int) -> int:
    """Return the signed number of milliseconds from ``start`` to ``end``.

    The result is positive when ``end`` is later than ``start`` and negative when it is
    earlier, even when the clock rolled over between the two.
    ``ticks_diff(now_ms, deadline_ms) >= 0`` tests whether a deadline has passed.

    Args:
        end: The tick to measure to, usually the current one.
        start: The tick to measure from.

    Returns:
        Milliseconds from ``start`` to ``end``, from ``-TICKS_HALFPERIOD`` up to
            ``TICKS_HALFPERIOD - 1`` (2**28 is about 3.1 days).  Two ticks further apart
            than that come out with the wrong sign.
    """
    diff = (end - start) & TICKS_MAX
    return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD
