"""Suspension helpers for runner-driven generators.

``sleep_until`` suspends a generator registered via ``Runner.add_generator`` until an absolute tick arrives.
"""


class _DeadlineWait:
    def __init__(self, until_ms: int) -> None:
        self._until_ms = until_ms

    def next_deadline(self, now_ms: int) -> int | None:
        return self._until_ms


def sleep_until(until_ms: int) -> object:
    """Suspend the generator until ``ticks_ms() >= until_ms``.

    Does no time math of its own: it publishes the deadline and the driver decides
    when to resume, comparing with the clock it was built on.  That keeps a sleep
    measured in the units of the clock passed to ``Runner(ticks=...)`` rather than
    a second one this module reached for.

    Args:
        until_ms: Absolute tick value at which to resume, in the driver's units.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    yield _DeadlineWait(until_ms)
