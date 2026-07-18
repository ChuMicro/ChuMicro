"""Test helpers for libraries that use chumicro-runner.

Provides ``CallRecorder`` (records handler invocations) and
``FakePoller`` (host-test stand-in for ``select.poll().ipoll``).
"""

__chumicro_test_support__ = True


class FakePoller:
    """Host-test fake for ``select.poll().ipoll``."""

    def __init__(self) -> None:
        self.registered: dict = {}
        self.register_calls: list = []
        self.modify_calls: list = []
        self.unregister_calls: list = []
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
    """Callable that records each invocation for test assertions."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, now_ms: int) -> None:
        self.calls.append(now_ms)

    def __len__(self) -> int:
        return len(self.calls)

    def clear(self) -> None:
        """Discard all recorded calls."""
        self.calls.clear()
