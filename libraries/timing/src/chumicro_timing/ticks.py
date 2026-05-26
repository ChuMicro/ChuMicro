"""Wraps a millisecond tick counter into the 29-bit wrap arithmetic shared across runtimes."""

import time

try:
    from micropython import const
except ImportError:
    # Stands in for ``micropython.const`` on CPython so the module evaluates everywhere.
    def const(value):
        return value


# Counts the distinct tick values; 2**29 matches MicroPython's ``time.ticks_ms`` wrap.
TICKS_PERIOD = const(1 << 29)
# Masks any raw counter down to the wrap range.
TICKS_MAX = const(TICKS_PERIOD - 1)
# Splits the wrap range so ``ticks_diff`` can sign a result around the midpoint.
TICKS_HALFPERIOD = const(TICKS_PERIOD // 2)


def _resolve_ticks_ms() -> object:
    """Picks the best-available millisecond tick source from the active runtime."""
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


# Caches the resolved tick source so each call avoids the runtime probe.
_raw_ticks_ms = _resolve_ticks_ms()


def ticks_ms() -> int:
    """Reads the current millisecond tick, masked into the 29-bit wrap range."""
    return _raw_ticks_ms() & TICKS_MAX


def ticks_add(ticks: int, delta: int) -> int:
    """Advances ``ticks`` by ``delta`` milliseconds and wraps the result.

    Args:
        ticks: A tick value in the 29-bit wrap range.
        delta: A signed millisecond offset strictly inside ``+/- TICKS_HALFPERIOD``.

    Returns:
        The wrapped sum, in the same range as ``ticks``.

    Raises:
        OverflowError: When ``delta`` reaches or exceeds half the wrap period.
    """
    if -TICKS_HALFPERIOD < delta < TICKS_HALFPERIOD:
        return (ticks + delta) % TICKS_PERIOD
    raise OverflowError("ticks interval overflow")


def ticks_diff(end: int, start: int) -> int:
    """Reports ``end - start`` in milliseconds, signed across the 29-bit wrap.

    Args:
        end: The later tick reading.
        start: The earlier tick reading.

    Returns:
        A signed millisecond delta in ``[-TICKS_HALFPERIOD, TICKS_HALFPERIOD)``.
    """
    diff = (end - start) & TICKS_MAX
    return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD
