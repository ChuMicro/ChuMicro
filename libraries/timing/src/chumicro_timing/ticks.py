"""Cross-runtime millisecond tick helpers.

Provides wraparound-safe tick functions that work identically on
CircuitPython, MicroPython, and CPython.  The API mirrors MicroPython's
``time.ticks_ms`` / ``time.ticks_diff`` / ``time.ticks_add`` contract
with a fixed wrap period of 2**29 ms (~6.2 days).

The 2**29 period keeps add/subtract results below 2**30, avoiding
heap-allocated long integers on boards without big-int support.

Design note
-----------
The wraparound-safe tick contract and the 2**29 period originate from
MicroPython's ``time`` module and are also used by Adafruit's
``adafruit_ticks`` library (MIT-licensed).  This module is an
independent implementation written from the mathematical specification
of modular/ring arithmetic for tick counters.
"""

import time

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# const() on a public name keeps both wins on MicroPython: the use
# sites get inlined as compile-time literals, AND the name remains
# importable from this module (which testing.py relies on for the
# cross-runtime test runs).  Only the leading-underscore form
# additionally strips the module-level binding.
TICKS_PERIOD = const(1 << 29)
TICKS_MAX = const(TICKS_PERIOD - 1)
TICKS_HALFPERIOD = const(TICKS_PERIOD // 2)


def _resolve_ticks_ms() -> object:
    """Choose the best raw millisecond source available on this runtime.

    Called once at import time.  The returned callable is stored in
    ``_raw_ticks_ms`` and invoked by ``ticks_ms()`` on every call.

    Resolution order:
      1. ``supervisor.ticks_ms`` — CircuitPython 7+
      2. ``time.ticks_ms`` — MicroPython (and CP unix port)
      3. ``time.monotonic_ns`` — CPython, some CP Express boards
      4. ``time.monotonic`` — final fallback (float seconds)
    """
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
    """Return a monotonic millisecond count in [0 .. 2**29 - 1].

    Values wrap every ~6.2 days.  Use ``ticks_diff`` and ``ticks_add``
    for arithmetic; plain subtraction gives wrong results near the
    wrap boundary.
    """
    return _raw_ticks_ms() & TICKS_MAX


def ticks_add(ticks: int, delta: int) -> int:
    """Add *delta* milliseconds to a tick value, wrapping at 2**29.

    Args:
        ticks: Base tick value.
        delta: Milliseconds to add.

    Returns:
        Wrapped tick value.

    Raises:
        OverflowError: If *delta* is outside (-2**28 .. 2**28).
    """
    if -TICKS_HALFPERIOD < delta < TICKS_HALFPERIOD:
        return (ticks + delta) % TICKS_PERIOD
    raise OverflowError("ticks interval overflow")


def ticks_diff(end: int, start: int) -> int:
    """Signed difference *end* minus *start* with wraparound handling.

    Correct as long as *end* and *start* are no more than
    2**28 ms (~3.1 days) apart.

    Args:
        end: Later tick value.
        start: Earlier tick value.

    Returns:
        Signed difference in milliseconds.
    """
    diff = (end - start) & TICKS_MAX
    return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD
