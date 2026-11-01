"""Host-test helpers for code on a ``Runner``: ``validate_service``, ``FakePoller``, and ``CallRecorder``."""

__chumicro_test_support__ = True


def validate_service(service: object) -> None:
    """Raise ``ValueError`` when ``service`` lacks a member ``Runner`` needs, or has one without its partner.

    ``validate_service`` reads which members the service defines and calls none of them, so
    it is safe on a service wired to hardware.  It checks that:

    * ``check`` and ``handle`` are both callable.
    * ``io_socket`` and ``io_interest`` come together.  ``Runner.wait`` watches the socket
      only through ``io_interest``.
    * ``io_error`` comes with an ``io_socket``, the socket whose poll errors it receives.

    ``Runner.add`` accepts a service that breaks either of the last two rules, and the
    service's socket hooks then never run.  ``next_deadline`` is optional and stands
    alone.  ``io_socket`` is a plain attribute holding the socket, or None before it
    connects.  The other members are methods.

    Args:
        service: The object you would pass to ``Runner.add``.

    Raises:
        ValueError: A rule is broken.  The message names the member at fault.
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
    """A stand-in for ``select.poll()`` that records what ``Runner.wait`` asks it to watch.

    Pass it as ``Runner(poller=FakePoller())``.  ``set_ready`` queues the events the next
    ``ipoll`` returns, and ``ipoll`` returns at once.

    Attributes:
        registered: The objects being watched now, keyed by ``id(obj)``, each as an
            ``(obj, eventmask)`` pair.
        register_calls: Every ``(obj, eventmask)`` passed to ``register``, oldest first.
        modify_calls: Every ``(obj, eventmask)`` passed to ``modify``, oldest first.
        unregister_calls: Every object passed to ``unregister``, oldest first.
        ipoll_calls: Every ``timeout_ms`` passed to ``ipoll``, oldest first.
    """

    def __init__(self) -> None:
        self.registered: dict = {}
        self.register_calls: list = []
        self.modify_calls: list = []
        self.unregister_calls: list = []
        self.ipoll_calls: list = []
        self._ready: list = []

    def register(self, obj: object, eventmask: int) -> None:
        """Start watching ``obj`` for ``eventmask`` and record the call."""
        self.registered[id(obj)] = (obj, eventmask)
        self.register_calls.append((obj, eventmask))

    def modify(self, obj: object, eventmask: int) -> None:
        """Change the ``eventmask`` ``obj`` is watched for and record the call."""
        self.registered[id(obj)] = (obj, eventmask)
        self.modify_calls.append((obj, eventmask))

    def unregister(self, obj: object) -> None:
        """Stop watching ``obj`` and record the call."""
        self.registered.pop(id(obj), None)
        self.unregister_calls.append(obj)

    def ipoll(self, timeout_ms: int) -> list:
        """Record ``timeout_ms`` and return the ``(obj, eventmask)`` pairs queued since the last call."""
        self.ipoll_calls.append(timeout_ms)
        ready = self._ready
        self._ready = []
        return ready

    def set_ready(self, obj: object, eventmask: int) -> None:
        """Queue ``obj`` with ``eventmask`` for the next ``ipoll`` to return."""
        self._ready.append((obj, eventmask))


class CallRecorder:
    """A job function that records the ``now_ms`` of every call, for a test to assert on.

    Register it anywhere a handler goes, such as ``runner.add_periodic(recorder, period_ms=100)``.
    ``len(recorder)`` is the number of calls so far.

    Attributes:
        calls: The ``now_ms`` of each call, oldest first.
    """

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, now_ms: int) -> None:
        self.calls.append(now_ms)

    def __len__(self) -> int:
        return len(self.calls)

    def clear(self) -> None:
        """Forget every recorded call."""
        self.calls.clear()
