"""Test helpers for libraries that use chumicro-runner.

Provides ``CallRecorder`` — a callable that records handler invocations
for assertion in host-side tests.

Ships with the library per Decision 0010 so downstream consumers
import ready-made fakes rather than inventing ad-hoc mocks.

Example:
    ```python
    from chumicro_runner.testing import CallRecorder

    recorder = CallRecorder()
    runner.add_periodic(recorder, period_ms=100)
    # ... advance time, tick() ...
    assert recorder.calls == [100]
    ```
"""


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
