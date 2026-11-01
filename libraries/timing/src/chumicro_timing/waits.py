"""``Signal`` and ``wait_for``: pause a generator task until a callback reports that something finished.

Import them from ``chumicro_timing.waits``.  ``import chumicro_timing`` leaves this module
unloaded, so a program with no generator tasks spends no RAM on it.
"""

import errno

from chumicro_timing.ticks import ticks_diff


class Signal:
    """A flag a callback sets and a generator task waits on, carrying one value across.

    The callback calls ``set(value)`` when its event happens, and the generator paused in
    ``yield from wait_for(signal)`` resumes with that value.  A second ``set`` before the
    generator resumes replaces the first value.  Call ``clear`` before waiting on the same
    signal again.

    Attributes:
        is_set: True from ``set`` until ``clear``.
        value: The value passed to the last ``set``, or None.
    """

    def __init__(self) -> None:
        self.is_set = False
        self.value = None
        self._deadline_ms: int | None = None

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the tick at which a bounded ``wait_for`` gives up, or None for an unbounded wait.

        The generator's driver, a ``Runner`` or a hand-written loop, reads this to wake the
        generator in time to raise its timeout.
        """
        return self._deadline_ms

    def set(self, value: object = None) -> None:
        """Mark the signal set and store ``value`` for the waiting generator to receive."""
        self.value = value
        self.is_set = True

    def clear(self) -> None:
        """Mark the signal unset and drop its stored value, ready for the next wait."""
        self.is_set = False
        self.value = None

    def ready(self, now_ms: int) -> bool:
        """Return True once ``set`` has run, which tells the generator's driver to resume it.

        ``ready`` ignores ``now_ms`` and the deadline.  The driver, a ``Runner`` or a
        hand-written loop, compares ``next_deadline`` with its own clock and resumes the
        generator once that tick passes, so a bounded wait times out on the driver's clock.
        """
        return self.is_set


def wait_for(signal: Signal, *, deadline_ms: int | None = None) -> object:
    """Pause the calling generator until ``signal`` is set, then return the value it carries.

    Call it as ``value = yield from wait_for(signal)`` inside a generator task.  A signal
    that is already set returns at once.  ``wait_for`` leaves the signal set, so call
    ``signal.clear()`` before waiting on it again.

    Args:
        signal: The ``Signal`` to wait on.
        deadline_ms: The tick at which to give up, such as
            ``ticks_add(ticks_ms(), 5000)`` for five seconds, or None to wait forever.

    Yields:
        ``signal`` itself, once per pause, for the driver to check.

    Returns:
        The value passed to ``signal.set``.

    Raises:
        OSError: ``OSError(errno.ETIMEDOUT)`` once ``deadline_ms`` passes with the signal
            still unset.
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
