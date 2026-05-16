"""Test helpers for libraries that consume chumicro-logging.

The library itself doesn't need fakes — its handlers are already
trivial to substitute (any object exposing ``emit(level, name,
message)`` works).  This module ships two helpers — ``RecordingHandler``
and ``FailingHandler`` — that are useful when *downstream* libraries
want to assert against logger output without writing one-off mocks.
See ``docs/testing.md`` for worked examples.

The helpers are test-support — the ``__chumicro_test_support__``
marker below keeps this file out of every bundle and every product /
app / functional device deploy (the on-device unit sweep stages it).
"""

#: Source bundle / sdist only -- never lands on a device.
__chumicro_test_support__ = True


class RecordingHandler:
    """Handler that captures records in a list for test assertions.

    Each call to ``emit`` appends ``(level, name, message)``.  The
    list is exposed as ``records`` and can be inspected, asserted
    against, or cleared via ``clear()``.

    Args:
        level: Minimum level captured.  Defaults to ``0`` so every
            record passes through regardless of logger threshold.
    """

    def __init__(self, level: int = 0) -> None:
        self._level = level
        self._records: list = []

    @property
    def level(self) -> int:
        """Current minimum-capture level."""
        return self._level

    @level.setter
    def level(self, value: int) -> None:
        self._level = value

    @property
    def records(self) -> list:
        """All captured records as ``(level, name, message)`` tuples."""
        return list(self._records)

    def clear(self) -> None:
        """Drop all captured records."""
        self._records = []

    def emit(self, level: int, name: str, message: str) -> None:
        """Capture the record if it meets the level threshold."""
        if level < self._level:
            return
        self._records.append((level, name, message))


class FailingHandler:
    """Handler that raises on every ``emit`` — used to exercise error paths.

    The Logger's ``handler_errors`` counter increments each time this
    fires.  Useful for asserting that a misbehaving handler never
    crashes the application.

    Args:
        exception: The exception instance to raise.  Defaults to
            ``RuntimeError("handler boom")``.
    """

    def __init__(self, exception: BaseException | None = None) -> None:
        self._exception = exception if exception is not None else RuntimeError("handler boom")
        self._calls = 0

    @property
    def calls(self) -> int:
        """Number of times ``emit`` has been called."""
        return self._calls

    def emit(self, level: int, name: str, message: str) -> None:
        """Increment the call counter and raise the configured exception."""
        self._calls += 1
        raise self._exception
