"""Test fakes for the device transport layer.

Provides ``FakeTransport`` — a transport implementation that records
all calls and returns configurable output.  Use it in host-side tests
that need to verify orchestration logic without touching real hardware.

Also provides ``FakeSerialPort`` for testing ``CircuitpythonTransport``
internals without real hardware::

    from chumicro_device_transport.testing import FakeSerialPort
    from chumicro_testing import FakeTime
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["FakeSerialPort", "FakeTransport"]


class FakeSerialPort:
    """Simulates a pyserial Serial port for transport testing.

    Records all writes and returns canned responses for reads.
    """

    def __init__(
        self,
        *,
        read_responses: list[bytes] | None = None,
        open_error: Exception | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self._read_responses = list(read_responses or [])
        self._read_index = 0
        self._open_error = open_error

    @property
    def in_waiting(self) -> int:
        """Return how many bytes are available to read."""
        if self._read_index < len(self._read_responses):
            return len(self._read_responses[self._read_index])
        return 0

    def read(self, size: int = 1) -> bytes:
        """Return the next canned response."""
        if self._read_index < len(self._read_responses):
            data = self._read_responses[self._read_index]
            self._read_index += 1
            return data
        return b""

    def write(self, data: bytes) -> int:
        """Record a write."""
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        """Mark the port as closed."""
        self.closed = True

    def reset_input_buffer(self) -> None:
        """No-op for fake."""


@dataclass
class FakeTransport:
    """In-memory fake that records transport calls and returns canned output.

    Attributes:
        execute_output: The string returned by ``execute()``.
        calls: List of ``(method_name, args_tuple)`` recording every call.
        connected: Whether ``connect()`` has been called without a
            subsequent ``disconnect()``.
    """

    execute_output: str = ""
    calls: list[tuple[str, tuple]] = field(default_factory=list)
    connected: bool = False

    def connect(self) -> None:
        """Record a connect call."""
        self.calls.append(("connect", ()))
        self.connected = True

    def stage(self, source_dirs, test_files, harness_source) -> None:
        """Record a stage call.

        Args:
            source_dirs: Library source directories.
            test_files: Test file paths.
            harness_source: Harness source directory.
        """
        self.calls.append(("stage", (source_dirs, test_files, harness_source)))

    def execute(self, bootstrap_script: str) -> str:
        """Record an execute call and return canned output.

        Args:
            bootstrap_script: The bootstrap code string.

        Returns:
            The configured ``execute_output``.
        """
        self.calls.append(("execute", (bootstrap_script,)))
        return self.execute_output

    def reset(self) -> None:
        """Record a reset call."""
        self.calls.append(("reset", ()))

    def disconnect(self) -> None:
        """Record a disconnect call."""
        self.calls.append(("disconnect", ()))
        self.connected = False

