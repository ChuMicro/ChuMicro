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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DeviceImplementation:
    """Runtime identity probed from a connected board.

    Populated by ``probe_implementation`` on transports that support it
    (both :class:`MicropythonTransport` and :class:`CircuitpythonTransport`
    do).  Consumed by the ``test-device`` PR-summary output so reviewers
    see the exact firmware version and board model that exercised the
    tests — without contributors having to hand-fill the template.

    Attributes:
        name: ``sys.implementation.name`` — ``"circuitpython"`` or
            ``"micropython"``.
        version: Dotted version from ``sys.implementation.version``
            (e.g. ``"10.1.4"`` or ``"1.26.0"``).
        machine: ``sys.implementation._machine`` on both runtimes —
            a free-form string describing the board (e.g.
            ``"Raspberry Pi Pico W with rp2040"``).  Empty when the
            firmware does not expose it.
    """

    name: str
    version: str
    machine: str


#: On-device probe script.  Prints one ``__CHU_IMPL__:`` line with
#: pipe-delimited ``name|version|machine`` so the host can locate the
#: probe output among any incidental boot banners.  Uses only
#: ``sys.implementation`` which exists on both CircuitPython and
#: MicroPython and needs no staged files — safe to run immediately
#: after ``connect()``.
PROBE_IMPLEMENTATION_SCRIPT = (
    "import sys\n"
    "_probe_version = sys.implementation.version\n"
    "_probe_machine = getattr(sys.implementation, '_machine', '')\n"
    "print('__CHU_IMPL__:' + sys.implementation.name"
    " + '|' + '.'.join(str(_probe_part) for _probe_part in _probe_version)"
    " + '|' + _probe_machine)\n"
)


def parse_probe_output(output: str) -> DeviceImplementation | None:
    """Extract a :class:`DeviceImplementation` from probe stdout.

    Scans for the ``__CHU_IMPL__:`` marker line emitted by
    :data:`PROBE_IMPLEMENTATION_SCRIPT` and ignores any surrounding
    output.  Returns ``None`` when the marker is missing or the
    payload is malformed — callers treat that as "probe unavailable"
    and fall back to per-device metadata from ``devices.yml``.

    Args:
        output: Combined stdout (and stderr if merged) from the probe
            script's ``execute`` call.
    """
    for line in output.splitlines():
        if not line.startswith("__CHU_IMPL__:"):
            continue
        payload = line[len("__CHU_IMPL__:"):]
        parts = payload.split("|", 2)
        if len(parts) != 3:
            return None
        name, version, machine = parts
        return DeviceImplementation(
            name=name.strip(),
            version=version.strip(),
            machine=machine.strip(),
        )
    return None


@runtime_checkable
class TransportProtocol(Protocol):
    """Minimum transport contract every device transport must satisfy."""

    #: User-facing deploy mode label.  ``"ram"`` / ``"flash"`` for
    #: CircuitPython, ``"mount"`` / ``"copy"`` for MicroPython.  The
    #: orchestration layer branches on this to decide per-library vs.
    #: bulk staging, soft-reset cadence, and inline vs. import bootstraps.
    mode: str

    def connect(self) -> None:
        """Verify the device is reachable."""
        ...

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
    ) -> None:
        """Prepare the host-side staging area and (mode-dependent) push to device."""
        ...

    def execute(self, bootstrap_script: str) -> str:
        """Run *bootstrap_script* on the device and return captured stdout."""
        ...

    def soft_reset(self) -> None:
        """Soft-reset the interpreter to clear modules and free heap."""
        ...

    def reset(self) -> None:
        """Planned reset between healthy library groups."""
        ...

    def recover(self) -> None:
        """Aggressive reset after a failure when board state is unknown."""
        ...

    def disconnect(self) -> None:
        """Release transport resources (serial port, mounts, staging dir)."""
        ...

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata."""
        ...

    def reset_into_bootloader(self) -> bool:
        """Try to put the board into its UF2 bootloader via the running runtime.

        Called by :func:`~chumicro_deploy.firmware.flash_firmware`
        before it begins polling for the bootloader drive.  The
        implementation issues a runtime-specific reset command
        (``machine.bootloader()`` on MicroPython,
        ``microcontroller.on_next_reset(RunMode.BOOTLOADER)`` +
        ``microcontroller.reset()`` on CircuitPython) and swallows
        the connection-drop that follows — the serial link is torn
        down as the board resets, so a clean response is not
        expected.

        Returns:
            ``True`` when the command was dispatched (the board
            should be rebooting into its bootloader).
            ``False`` when the runtime does not expose a
            bootloader-entry API, the transport could not be opened,
            or the command failed before reaching the board.
            Callers fall back to an interactive prompt in the
            ``False`` case.
        """
        ...

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
    ) -> str:
        """Write files onto the device and execute the entrypoint.

        Distinct from :meth:`stage` + :meth:`execute` — the former pair
        is test-harness-shaped (dirs + test files + harness source),
        while this method takes a generic path-to-bytes map and a
        single entrypoint path.  Used by :class:`Deployer` and by any
        third party shipping an app rather than running tests.

        Args:
            files: On-device-path -> file-bytes mapping.  Paths may
                start with ``/``; transports normalise as needed.
            entrypoint: On-device path (must be a key of *files*) for
                the runtime to execute after staging.
            on_file_staged: Optional per-file callback invoked with
                the on-device path as each file is written.
            on_execute_line: Optional callback invoked once per line
                of captured execute output, in order.  Not guaranteed
                to stream live — transports may call it after
                execute() completes.

        Returns:
            Combined stdout from the entrypoint execution.
        """
        ...


@runtime_checkable
class ExtendedTransportProtocol(TransportProtocol, Protocol):
    """Transport contract plus the CircuitPython RAM-mode chunking helpers.

    Implemented by :class:`CircuitpythonTransport`; orchestrators (and
    test fakes that exercise the chunked path) check for this protocol
    before calling the chunked-execute helpers.
    """

    #: Module sources captured by ``stage()`` for RAM-mode inline
    #: execution.  Each entry is ``(dotted_module_name, source_text)``.
    #: ``None`` before ``stage()`` has been called.
    staged_sources: list[tuple[str, str]] | None

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Run multiple bootstrap scripts in one interpreter session."""
        ...

    def probe_free_memory(self) -> int:
        """Return free heap bytes reported by the connected board."""
        ...

    def inline_script_budget_bytes(self) -> int:
        """Return a conservative per-script budget based on live free heap."""
        ...
