"""Time-based suspension helper for runner-driven generators.

Opt-in submodule — import explicitly::

    from chumicro_runner.generators import sleep_until

``sleep_until`` suspends a generator registered via
``Runner.add_generator`` until an absolute tick arrives.  It is the
scheduler-side companion to the socket I/O generator helpers in
``chumicro_sockets.generators``; the socket helpers gate on poll
readiness, this one gates on a deadline.
"""


class _DeadlineWait:
    """Private deadline-wait shape — ``next_deadline=until_ms``."""

    def __init__(self, until_ms: int) -> None:
        self.next_deadline = until_ms


def sleep_until(until_ms: int) -> object:
    """Suspend the generator until ``ticks_ms() >= until_ms``.

    The wrapper reads ``next_deadline`` off the yielded wait and
    contributes it to ``Runner.wait``'s ipoll timeout so the loop
    sleeps efficiently between sleep-only services.

    Compute *until_ms* via ``ticks_add(ticks_ms(), delay_ms)`` —
    treating it as an absolute tick (wrap-safe) rather than a delay
    means a single yield won't drift across long pauses.

    Args:
        until_ms: Absolute ``ticks_ms`` value at which to resume.

    Yields:
        A private deadline-wait carrying *until_ms*.
    """
    yield _DeadlineWait(until_ms)
