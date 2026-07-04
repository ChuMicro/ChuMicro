"""Shared test helpers for the split ``test_core_*`` cross-runtime suites.

Underscore-prefixed so the harness never collects it as a test module.
The harness puts each test file's directory on ``sys.path``, so the split
files import these with ``from _core_helpers import ...`` on CPython,
MicroPython, and CircuitPython alike.
"""

from chumicro_runner import IO_READ, IO_WRITE


class _GateTask:
    """Minimal gate-based task component for testing."""

    def __init__(self, should_fire: bool = True) -> None:
        """Create a stub that returns *should_fire* from check()."""
        self.should_fire = should_fire
        self.check_count = 0
        self.handle_count = 0

    def check(self, now_ms: int) -> bool:
        """Return whether the handler should fire."""
        self.check_count += 1
        return self.should_fire

    def handle(self, now_ms: int) -> None:
        """Record that the handler was called."""
        self.handle_count += 1


class _IOService:
    """Stub I/O service exposing the duck-typed ``io_socket`` +
    ``io_interest(now_ms)`` surface that ``Runner.wait`` reads each loop.

    ``wants_read`` / ``wants_write`` are mutable bool knobs a test flips
    to change the service's interest; ``io_interest`` maps them to the
    ``IO_READ`` / ``IO_WRITE`` bitmask the runner consumes."""

    def __init__(self, sock: object | None = None,
                 wants_read: bool = False,
                 wants_write: bool = False) -> None:
        self.io_socket = sock
        self.wants_read = wants_read
        self.wants_write = wants_write
        self.check_returns = False
        self.handle_count = 0

    def io_interest(self, now_ms: int) -> int:
        interest = 0
        if self.wants_read:
            interest |= IO_READ
        if self.wants_write:
            interest |= IO_WRITE
        return interest

    def check(self, now_ms: int) -> bool:
        return self.check_returns

    def handle(self, now_ms: int) -> None:
        self.handle_count += 1


class _IOServiceWithErrorHook(_IOService):
    """``_IOService`` plus an ``io_error`` hook that records calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.io_error_calls: list[tuple[int, int]] = []

    def io_error(self, now_ms: int, eventmask: int) -> None:
        self.io_error_calls.append((now_ms, eventmask))
