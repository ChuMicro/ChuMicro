"""Cross-runtime wrap-safe millisecond ticks and signed-difference math; values wrap every ~6.2 days."""

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
    """Returns the current tick in ``[0, TICKS_MAX]``; compare with ``ticks_diff``, not subtraction."""
    return _raw_ticks_ms() & TICKS_MAX


def ticks_add(ticks: int, delta: int) -> int:
    """Returns ``ticks`` advanced by ``delta`` within the wrap-safe range.

    Raises:
        OverflowError: When ``delta`` reaches half a period (~3.1 days) in either direction.
    """
    if -TICKS_HALFPERIOD < delta < TICKS_HALFPERIOD:
        return (ticks + delta) % TICKS_PERIOD
    raise OverflowError("ticks interval overflow")


def ticks_diff(end: int, start: int) -> int:
    """Returns the signed millisecond distance from ``start`` to ``end``.

    Returns:
        Signed value in ``[-TICKS_HALFPERIOD, TICKS_HALFPERIOD)``; gaps over ~3.1 days
        (half the wrap period) alias to the wrong sign.
    """
    diff = (end - start) & TICKS_MAX
    return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD
