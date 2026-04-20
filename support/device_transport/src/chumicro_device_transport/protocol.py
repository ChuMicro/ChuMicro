"""Explicit transport protocol for ChuMicro device transports.

Decision 0027 documents the duck-typed transport contract in prose.
This module makes the same contract enforceable by type checkers.

Two protocols are defined:

- :class:`TransportProtocol` — the minimum every transport must
  implement: ``connect``, ``stage``, ``execute``, ``soft_reset``,
  ``reset``, ``recover``, ``disconnect``.
- :class:`ExtendedTransportProtocol` — adds the
  CircuitPython-specific RAM-mode chunking helpers
  (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).  ``MicropythonTransport`` does not
  need these — there is no per-script RAM budget on mpremote.

CPython-only — these protocols ride on ``typing.Protocol`` which the
support package can use freely (``support/device_transport`` is not
constrained to the embedded-runtime subset).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class TransportProtocol(Protocol):
    """Minimum transport contract every device transport must satisfy."""

    def connect(self) -> None:
        """Verify the device is reachable."""

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
    ) -> None:
        """Prepare the host-side staging area and (mode-dependent) push to device."""

    def execute(self, bootstrap_script: str) -> str:
        """Run *bootstrap_script* on the device and return captured stdout."""

    def soft_reset(self) -> None:
        """Soft-reset the interpreter to clear modules and free heap."""

    def reset(self) -> None:
        """Planned reset between healthy library groups."""

    def recover(self) -> None:
        """Aggressive reset after a failure when board state is unknown."""

    def disconnect(self) -> None:
        """Release transport resources (serial port, mounts, staging dir)."""


@runtime_checkable
class ExtendedTransportProtocol(TransportProtocol, Protocol):
    """Transport contract plus the CircuitPython RAM-mode chunking helpers.

    Implemented by :class:`CircuitpythonTransport`; orchestrators (and
    test fakes that exercise the chunked path) check for this protocol
    before calling the chunked-execute helpers.
    """

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Run multiple bootstrap scripts in one interpreter session."""

    def probe_free_memory(self) -> int:
        """Return free heap bytes reported by the connected board."""

    def inline_script_budget_bytes(self) -> int:
        """Return a conservative per-script budget based on live free heap."""
