"""``sleep_until``: pause a generator task until a given tick.

Import it from ``chumicro_runner.generators``.  ``import chumicro_runner`` leaves this module
unloaded, so a program with no generator tasks spends no RAM on it.
"""


class _DeadlineWait:
    def __init__(self, until_ms: int) -> None:
        self._until_ms = until_ms

    def next_deadline(self, now_ms: int) -> int | None:
        return self._until_ms


def sleep_until(until_ms: int) -> object:
    """Pause the calling generator task until the clock reaches the tick ``until_ms``.

    Call it as ``yield from sleep_until(until_ms)`` inside a generator registered with
    ``Runner.add_generator``.  The runner runs its other jobs meanwhile, sleeps in ``wait``
    until ``until_ms`` if nothing else is due, and resumes the generator on the first tick
    at or after it.  To pause for a duration, pass ``ticks_add(ticks_ms(), duration_ms)``.

    Args:
        until_ms: The tick to resume at, on the clock the ``Runner`` was built with.

    Yields:
        A wait object that carries ``until_ms`` for the runner to schedule against.
    """
    yield _DeadlineWait(until_ms)
