"""Suspension helpers for runner-driven generators.

``sleep_until`` suspends a generator registered via ``Runner.add_generator`` until an absolute tick arrives.
"""

from chumicro_timing.ticks import ticks_diff


class _DeadlineWait:
    def __init__(self, until_ms: int) -> None:
        self._until_ms = until_ms

    def ready(self, now_ms: int) -> bool:
        return ticks_diff(now_ms, self._until_ms) >= 0

    def next_deadline(self, now_ms: int) -> int | None:
        return self._until_ms


def sleep_until(until_ms: int) -> object:
    """Suspend the generator until ``ticks_ms() >= until_ms``.

    The deadline is enforced here rather than trusted to the driver, so a scheduler
    that resumes the generator early re-suspends instead of returning short.  One
    wait object is built and re-yielded, keeping a long sleep allocation-free.

    Args:
        until_ms: Absolute ``ticks_ms`` value at which to resume.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    wait = _DeadlineWait(until_ms)
    now_ms = yield wait
    while not wait.ready(now_ms):
        now_ms = yield wait
