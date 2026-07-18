"""Scheduler-side suspension helper for runner-driven generators.

Import explicitly::

    from chumicro_runner.generators import sleep_until

``sleep_until`` suspends a generator registered via
``Runner.add_generator`` until an absolute tick arrives.
"""


class _DeadlineWait:
    # A wait exposing only next_deadline: no socket, no ready predicate,
    # so the wrapper suspends the generator until this tick elapses.

    def __init__(self, until_ms: int) -> None:
        self._until_ms = until_ms

    def next_deadline(self, now_ms: int) -> int | None:
        return self._until_ms


def sleep_until(until_ms: int) -> object:
    """Suspend the generator until ``ticks_ms() >= until_ms``.

    Compute *until_ms* as ``ticks_add(ticks_ms(), delay_ms)``: an absolute
    tick is wrap-safe, so a single yield will not drift across long pauses.

    Args:
        until_ms: Absolute ``ticks_ms`` value at which to resume.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    yield _DeadlineWait(until_ms)
