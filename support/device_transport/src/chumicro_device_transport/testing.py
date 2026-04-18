"""Test fakes for the device transport layer.

Provides ``FakeTransport`` — a transport implementation that records
all calls and returns configurable output.  Use it in host-side tests
that need to verify orchestration logic without touching real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

