"""Test helpers for libraries that consume chumicro-logging.

Provides ``RecordingHandler`` and ``FailingHandler``.
"""

#: Source bundle and sdist only; never lands on a device.
__chumicro_test_support__ = True


class RecordingHandler:
    """Handler that captures records in a list for test assertions.

    Args:
        level: Minimum level captured; defaults to ``0`` so every record passes.
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
    """Handler that raises on every ``emit``, to exercise error paths.

    Args:
        exception: Exception instance to raise; defaults to ``RuntimeError("handler boom")``.
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
