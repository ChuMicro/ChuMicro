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
except ImportError:  # CPython — const() is a no-op on standard Python.

    def const(value: int) -> int:
        """Identity fallback so ``const()`` works on CPython."""
        return value


_TICKS_PERIOD = const(1 << 29)
_TICKS_MAX = const(_TICKS_PERIOD - 1)
_TICKS_HALFPERIOD = const(_TICKS_PERIOD // 2)


def _try_import_supervisor() -> object | None:
    """Return the CircuitPython ``supervisor`` module, or ``None``."""
    try:
        import supervisor

        return supervisor
    except ImportError:
        return None


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
    supervisor = _try_import_supervisor()
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
    return _raw_ticks_ms() & _TICKS_MAX


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
    if -_TICKS_HALFPERIOD < delta < _TICKS_HALFPERIOD:
        return (ticks + delta) % _TICKS_PERIOD
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
    diff = (end - start) & _TICKS_MAX
    return ((diff + _TICKS_HALFPERIOD) & _TICKS_MAX) - _TICKS_HALFPERIOD
