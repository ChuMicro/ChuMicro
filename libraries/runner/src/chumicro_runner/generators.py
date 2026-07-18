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

    Args:
        until_ms: Absolute ``ticks_ms`` value at which to resume.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    yield _DeadlineWait(until_ms)
