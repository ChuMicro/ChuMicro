"""Completion-wait vocabulary: ``Signal`` and ``wait_for``."""

import errno

from chumicro_timing.ticks import ticks_diff


class Signal:
    """One-slot completion token connecting callback-style services to generator tasks."""

    def __init__(self) -> None:
        self.is_set = False
        self.value = None
        self._deadline_ms: int | None = None

    def next_deadline(self, now_ms: int) -> int | None:
        """Absolute tick deadline gating the wait, or ``None`` for indefinite."""
        return self._deadline_ms

    def set(self, value: object = None) -> None:
        """Complete the signal, storing *value* for the waiting generator."""
        self.value = value
        self.is_set = True

    def clear(self) -> None:
        """Re-arm for reuse: drop the stored value and the set flag."""
        self.is_set = False
        self.value = None

    def ready(self, now_ms: int) -> bool:
        """Return whether the waiting generator should resume.

        ``True`` once the signal is set, and also once a bounded wait's deadline has
        passed, so ``wait_for`` gets resumed and can raise ``ETIMEDOUT``.  Answering
        both cases here lets any driver gate on ``ready()`` alone.

        Args:
            now_ms: Current ``ticks_ms`` value.

        Returns:
            Whether the generator waiting on this signal should be resumed.
        """
        if self.is_set:
            return True
        deadline_ms = self._deadline_ms
        return deadline_ms is not None and ticks_diff(now_ms, deadline_ms) >= 0


def wait_for(signal: Signal, *, deadline_ms: int | None = None) -> object:
    """Suspend until *signal* is set; return the value it carries.

    Args:
        signal: Signal to wait on; not cleared on return.
        deadline_ms: Absolute ``ticks_ms`` deadline, or ``None`` to wait indefinitely.

    Yields:
        *signal* itself on each suspension.

    Returns:
        The value passed to ``signal.set``.

    Raises:
        OSError: ``ETIMEDOUT`` when *deadline_ms* elapses before the signal is set.
    """
    signal._deadline_ms = deadline_ms
    try:
        while not signal.is_set:
            now_ms = yield signal
            if (
                deadline_ms is not None
                and not signal.is_set
                and ticks_diff(now_ms, deadline_ms) >= 0
            ):
                raise OSError(errno.ETIMEDOUT)
    finally:
        signal._deadline_ms = None
    return signal.value
