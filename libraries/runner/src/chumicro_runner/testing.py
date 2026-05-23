"""Test helpers for libraries that use chumicro-runner.

Provides ``CallRecorder`` (records handler invocations) and
``FakePoller`` (host-test stand-in for ``select.poll().ipoll``).
"""

__chumicro_test_support__ = True


class FakePoller:
    """Host-test fake for ``select.poll().ipoll``.

    Use as ``Runner(poller=FakePoller())`` so unit tests can drive
    ``Runner.wait`` without a real OS poller (CPython's ``select.poll``
    needs real file descriptors that the in-memory fake sockets do
    not have).

    Records every ``register`` / ``modify`` / ``unregister`` / ``ipoll``
    call so tests can assert on what the runner did with the poll
    set.  ``set_ready(obj, eventmask)`` queues a ready pair for the
    next ``ipoll`` call.
    """

    def __init__(self) -> None:
        # Sock-id => (sock, eventmask) for what is currently registered.
        self.registered: dict = {}
        self.register_calls: list = []
        self.modify_calls: list = []
        self.unregister_calls: list = []
        # List of ``timeout_ms`` values each ``ipoll`` received.
        self.ipoll_calls: list = []
        self._ready: list = []

    def register(self, obj: object, eventmask: int) -> None:
        self.registered[id(obj)] = (obj, eventmask)
        self.register_calls.append((obj, eventmask))

    def modify(self, obj: object, eventmask: int) -> None:
        self.registered[id(obj)] = (obj, eventmask)
        self.modify_calls.append((obj, eventmask))

    def unregister(self, obj: object) -> None:
        self.registered.pop(id(obj), None)
        self.unregister_calls.append(obj)

    def ipoll(self, timeout_ms: int) -> list:
        """Record the call; return whatever ``set_ready`` queued."""
        self.ipoll_calls.append(timeout_ms)
        ready = self._ready
        self._ready = []
        return ready

    def set_ready(self, obj: object, eventmask: int) -> None:
        """Queue *obj* / *eventmask* for the next ``ipoll`` return."""
        self._ready.append((obj, eventmask))


class CallRecorder:
    """Callable that records each invocation for test assertions.

    Use as a handler passed to ``Runner.add()`` or
    ``add_periodic()``::

        recorder = CallRecorder()
        runner.add_periodic(recorder, period_ms=100)
        runner.tick()
        assert len(recorder) == 0  # not due yet
    """

    def __init__(self) -> None:
        """Create an empty recorder."""
        self.calls: list[int] = []

    def __call__(self, now_ms: int) -> None:
        """Record a call with the given timestamp.

        Args:
            now_ms: Tick value passed by the runner.
        """
        self.calls.append(now_ms)

    def __len__(self) -> int:
        """Return the number of recorded calls."""
        return len(self.calls)

    def clear(self) -> None:
        """Discard all recorded calls."""
        self.calls.clear()
