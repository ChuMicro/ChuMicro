"""Scheduler-side suspension helpers for runner-driven generators.

Opt-in submodule — import explicitly::

    from chumicro_runner.generators import Signal, sleep_until, wait_for

``sleep_until`` suspends a generator registered via
``Runner.add_generator`` until an absolute tick arrives; ``Signal`` +
``wait_for`` suspend it until a callback-style service reports a
one-time completion.  Both are scheduler-side companions to the socket
I/O generator helpers in ``chumicro_sockets.generators``: the socket
helpers gate on poll readiness, these gate on a deadline or an event.
"""

import errno

from chumicro_timing.ticks import ticks_diff


class Signal:
    """One-slot completion token connecting callback-style services to
    generator tasks.

    The completing side calls ``set(value)`` — typically from a service
    callback firing inside its own tick.  A generator suspended via
    ``yield from wait_for(signal)`` resumes on the following tick and
    receives the stored value.  ``clear()`` re-arms the instance, so
    one signal serves many sequential waits; a suspended wait allocates
    nothing per tick.

    ``next_deadline`` holds the optional timeout as an absolute
    ``ticks_ms`` value — ``wait_for`` manages it; leave it alone when
    yielding a signal directly.
    """

    def __init__(self) -> None:
        self.is_set = False
        self.value = None
        self.next_deadline: int | None = None

    def set(self, value: object = None) -> None:
        """Complete the signal, storing *value* for the waiting generator."""
        self.value = value
        self.is_set = True

    def clear(self) -> None:
        """Re-arm for reuse: drop the stored value and the set flag."""
        self.is_set = False
        self.value = None

    def ready(self, now_ms: int) -> bool:
        """Return whether the waiting generator should resume — True once set."""
        return self.is_set


def wait_for(signal: Signal, *, deadline_ms: int | None = None) -> object:
    """Suspend until *signal* is set; return the value it carries.

    Wire the completing side before suspending — hand ``signal.set``
    (or a small wrapper around it) to the service as its callback —
    then ``yield from``::

        link_up = Signal()
        wifi.on_state_change(lambda old, new: link_up.set(new))
        state = yield from wait_for(link_up)

    This is for one-time completions a sequential flow genuinely
    blocks on (a link coming up, a handshake finishing).  Reactive
    fan-out — callbacks set once, operations queued fire-and-forget —
    stays callbacks; do not wrap an ack a caller never blocks on.

    Args:
        signal: The signal to wait on.  Not cleared on return — call
            ``signal.clear()`` before reusing it for another wait.
        deadline_ms: Optional absolute ``ticks_ms`` deadline (compute
            via ``ticks_add(ticks_ms(), timeout_ms)``).  ``None``
            waits indefinitely.

    Yields:
        *signal* itself on each suspension.

    Returns:
        The value passed to ``signal.set``.

    Raises:
        OSError: ``ETIMEDOUT`` — *deadline_ms* elapsed before the
            signal was set.  Raised inside the generator body, so the
            generator catches it there or lets it end the task.
    """
    signal.next_deadline = deadline_ms
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
        signal.next_deadline = None
    return signal.value


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
