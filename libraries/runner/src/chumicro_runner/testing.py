"""Test helpers for libraries that use chumicro-runner.

Provides ``validate_service`` (asserts a service's runner-contract
shape), ``CallRecorder`` (records handler invocations), and
``FakePoller`` (host-test stand-in for ``select.poll().ipoll``).
"""

__chumicro_test_support__ = True


def validate_service(service: object) -> None:
    """Assert *service* has a coherent runner-service shape.

    Checks shape only, never behavior: it reads which contract members
    the service exposes and enforces the coherence rules the ``Runner``
    dispatch relies on. It never calls ``check`` / ``handle`` / any hook.

    The rules, as ``chumicro_runner.core`` enforces them:

    * ``check`` and ``handle`` are both required. ``Runner.add`` reads
      ``task.check`` and ``task.handle`` unconditionally, so a service
      missing either cannot register.
    * ``io_socket`` and ``io_interest`` come as a pair. The poll sync
      reads interest through ``io_interest`` and the socket through the
      ``io_socket`` attribute; one without the other never reaches the
      poller.
    * ``io_error`` requires ``io_socket``. It is dispatched only when the
      service's ``io_socket`` reports a poll error.

    ``next_deadline`` is optional and stands alone. ``io_socket`` is a
    data attribute (the socket itself, or ``None`` before connect); the
    other members are callables.

    Args:
        service: The object a consumer would pass to ``Runner.add``.

    Raises:
        ValueError: A required member is missing or a coherence rule is
            broken; the message names the offending member.
    """
    for name in ("check", "handle"):
        if not callable(getattr(service, name, None)):
            raise ValueError(
                f"a runner service must define a callable {name!r}",
            )
    has_socket = hasattr(service, "io_socket")
    has_interest = callable(getattr(service, "io_interest", None))
    if has_socket and not has_interest:
        raise ValueError(
            "a service with io_socket must also define io_interest; "
            "the runner polls the socket only through io_interest",
        )
    if has_interest and not has_socket:
        raise ValueError(
            "a service with io_interest must also expose io_socket; "
            "io_interest with no socket to poll never runs",
        )
    if callable(getattr(service, "io_error", None)) and not has_socket:
        raise ValueError(
            "a service with io_error must also expose io_socket; "
            "io_error fires only on that socket's poll errors",
        )


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
