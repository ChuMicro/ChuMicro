"""Test fakes for the device transport layer.

Provides ``FakeTransport`` — a transport implementation that records
all calls and returns configurable output.  Use it in host-side tests
that need to verify orchestration logic without touching real hardware.

Also provides ``FakeSerialPort`` for testing ``CircuitpythonTransport``
internals without real hardware::

    from chumicro_device_transport.testing import FakeSerialPort
    from chumicro_abstractions import FakeTime
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

    Implements both :class:`TransportProtocol` and the
    :class:`ExtendedTransportProtocol` (CircuitPython chunked-execution
    helpers) so tests for either path can use a single fake.  The
    chunked methods default to delegating to ``execute`` so callers
    that don't care about the chunked behavior get sensible defaults.

    Attributes:
        execute_output: The string returned by ``execute()``.
        mode: Deploy mode label (e.g. ``"ram"``, ``"flash"``, ``"mount"``,
            ``"copy"``).  Defaults to ``"ram"``.
        free_memory_bytes: The value returned by ``probe_free_memory()``
            and the basis for ``inline_script_budget_bytes()``.
        calls: List of ``(method_name, args_tuple)`` recording every call.
        connected: Whether ``connect()`` has been called without a
            subsequent ``disconnect()``.
    """

    execute_output: str = ""
    mode: str = "ram"
    #: Default ~64 KB matches the real CP transport's lower bound.
    free_memory_bytes: int = 64 * 1024
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

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Record a chunked-execute call and return the configured output.

        Mirrors :meth:`CircuitpythonTransport.execute_scripts`.  Records
        the full list of scripts as one call, then synthetic per-script
        ``execute`` entries so existing tests that count ``execute``
        invocations still work.
        """
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        last_output = self.execute_output
        for bootstrap_script in bootstrap_scripts:
            last_output = self.execute(bootstrap_script)
        return last_output

    def probe_free_memory(self) -> int:
        """Record a probe call and return the configured free-heap value."""
        self.calls.append(("probe_free_memory", ()))
        return self.free_memory_bytes

    def inline_script_budget_bytes(self) -> int:
        """Return half the configured free-memory budget (matches CP heuristic)."""
        self.calls.append(("inline_script_budget_bytes", ()))
        return max(8 * 1024, self.free_memory_bytes // 2)

    def reset(self) -> None:
        """Record a reset call."""
        self.calls.append(("reset", ()))

    def soft_reset(self) -> None:
        """Record a soft_reset call."""
        self.calls.append(("soft_reset", ()))

    def recover(self) -> None:
        """Record a recover call (post-failure recovery hook)."""
        self.calls.append(("recover", ()))

    def disconnect(self) -> None:
        """Record a disconnect call."""
        self.calls.append(("disconnect", ()))
        self.connected = False
