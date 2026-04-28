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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class Runtime(StrEnum):
    """Supported device runtime identifiers.

    Values round-trip as plain strings so ``Device(transport="circuitpython")``
    and ``Device(transport=Runtime.CIRCUITPYTHON)`` are interchangeable.
    CLI argparse choices, config-file loaders, and third-party callers
    should reference members of this enum rather than string literals
    to keep the allowed set in one place.
    """

    CIRCUITPYTHON = "circuitpython"
    MICROPYTHON = "micropython"


class DeployMode(StrEnum):
    """User-facing deploy-mode preference.

    ``RAM`` keeps edits off the board's flash (inline exec on
    CircuitPython, ``mount`` on MicroPython).  ``FLASH`` writes files
    persistently (CIRCUITPY drive copy on CircuitPython, ``copy`` on
    MicroPython).  The transport-internal mount-label mapping
    (``ram`` → ``mount``, ``flash`` → ``copy``) is handled in
    :meth:`~chumicro_deploy.device.Device.create_transport`.
    """

    RAM = "ram"
    FLASH = "flash"


class ReflashMethod(StrEnum):
    """Firmware reflash backend selection.

    ``UF2`` drives the UF2 bootloader drive path (Pi Pico family,
    TinyUF2 boards).  ``ESPTOOL`` shells out to ``esptool`` over
    serial for ESP32-family boards.  See
    :func:`~chumicro_deploy.firmware.flash_firmware` for the method
    selection guide.
    """

    UF2 = "uf2"
    ESPTOOL = "esptool"


@dataclass(frozen=True)
class DeviceImplementation:
    """Runtime identity probed from a connected board.

    Populated by ``probe_implementation`` on transports that support it
    (both :class:`MicropythonTransport` and :class:`CircuitpythonTransport`
    do).  Consumed by the ``test-libraries-functional`` PR-summary output so reviewers
    see the exact firmware version and board model that exercised the
    tests, and by :meth:`CircuitpythonTransport._verify_drive_for_board`
    to match a mounted CIRCUITPY drive to its connected board (so
    ``devices.yml`` doesn't have to pin a mount-order-dependent path).

    Attributes:
        name: ``sys.implementation.name`` — ``"circuitpython"`` or
            ``"micropython"``.
        version: Dotted version from ``sys.implementation.version``
            (e.g. ``"10.1.4"`` or ``"1.26.0"``).
        machine: ``sys.implementation._machine`` on both runtimes —
            a free-form string describing the board (e.g.
            ``"Raspberry Pi Pico W with rp2040"``).  Empty when the
            firmware does not expose it.
        uid: Hex-uppercase CPU / module unique ID, sourced from
            ``microcontroller.cpu.uid`` on CircuitPython and
            ``machine.unique_id()`` on MicroPython.  Matches the
            ``UID:...`` line CircuitPython writes to
            ``boot_out.txt`` on mount, so the host can disambiguate
            two identical boards that would otherwise share a
            ``machine`` string.  Empty on firmware too old to expose
            the probe path or if the probe itself raised.
    """

    name: str
    version: str
    machine: str
    uid: str = ""


#: On-device probe script.  Prints two marker lines:
#:
#: - ``__CHU_IMPL__:name|version|machine`` — parsed unchanged from its
#:   original three-field contract so a machine string that itself
#:   contains ``|`` (rare but legal) still round-trips intact.
#: - ``__CHU_UID__:<hex>`` — emitted on a best-effort basis from
#:   ``microcontroller.cpu.uid`` (CircuitPython) or
#:   ``machine.unique_id()`` (MicroPython); an empty value means the
#:   probe couldn't read a UID on this firmware.
#:
#: Uses only ``sys.implementation`` (present on both CP and MP) and
#: the UID modules above; needs no staged files and is safe to run
#: immediately after ``connect()``.
PROBE_IMPLEMENTATION_SCRIPT = (
    "import sys\n"
    "_probe_version = sys.implementation.version\n"
    "_probe_machine = getattr(sys.implementation, '_machine', '')\n"
    "_probe_uid = ''\n"
    "try:\n"
    "    if sys.implementation.name == 'circuitpython':\n"
    "        import microcontroller as _probe_mod\n"
    "        _probe_uid = _probe_mod.cpu.uid.hex().upper()\n"
    "    else:\n"
    "        import machine as _probe_mod\n"
    "        _probe_uid = _probe_mod.unique_id().hex().upper()\n"
    "except Exception:\n"
    "    pass\n"
    "print('__CHU_IMPL__:' + sys.implementation.name"
    " + '|' + '.'.join(str(_probe_part) for _probe_part in _probe_version)"
    " + '|' + _probe_machine)\n"
    "print('__CHU_UID__:' + _probe_uid)\n"
)


#: Top-level on-device files chumicro-deploy treats as managed.
#: A diff-deploy that doesn't see one of these in the new payload
#: removes the existing copy from the device.  Outside-scope files
#: (user-uploaded images, hand-edited boot.py, etc.) are never
#: touched.  Replaces the multi-thing-staging path retired in
#: workspace-ecosystem Slice 7 (`plans/next-up.md` "Replace
#: multi-thing staging with scoped diff-deploy").
DEPLOY_SCOPE_FILES: frozenset[str] = frozenset(
    {
        "/code.py",
        "/main.py",
        "/active.py",
        "/runtime_config.msgpack",
    },
)

#: Directory prefixes whose entire subtree is managed by deploy.
#: Anything below ``/lib/`` is host-deployed; anything else under
#: the device root is the user's territory.
DEPLOY_SCOPE_PREFIXES: tuple[str, ...] = ("/lib/",)


def is_in_deploy_scope(device_path: str) -> bool:
    """Return True when *device_path* falls inside the deploy's managed scope.

    Scope rule (Slice 7 follow-on, ``plans/next-up.md`` "Replace
    multi-thing staging with scoped diff-deploy"):

    * The four canonical entrypoint / state files
      (``/code.py``, ``/main.py``, ``/active.py``,
      ``/runtime_config.msgpack``) — see :data:`DEPLOY_SCOPE_FILES`.
    * Everything under ``/lib/`` — see :data:`DEPLOY_SCOPE_PREFIXES`.

    Anything else — user-uploaded images, manually-edited
    ``boot.py`` overrides, hand-tuned ``settings.toml`` knobs — is
    out of scope and survives every diff-deploy untouched.

    The check is path-shape only: callers should normalise their
    paths to leading-slash form before calling.
    """
    if device_path in DEPLOY_SCOPE_FILES:
        return True
    return any(device_path.startswith(prefix) for prefix in DEPLOY_SCOPE_PREFIXES)


def validate_entrypoint_in_files(
    files: Mapping[str, object],
    entrypoint: str,
    *,
    error_cls: type[Exception] = ValueError,
) -> None:
    """Raise *error_cls* if *entrypoint* is not a key of *files*.

    The canonical message text (``"entrypoint <name> missing from
    files ..."``) is pattern-matched by
    :func:`~chumicro_deploy.recovery.classify_deploy_failure` to route
    to :attr:`DeployFailureKind.CONFIGURATION_ERROR`, so every deploy
    layer routes through this helper to keep the classifier contract
    in one place.
    """
    if entrypoint not in files:
        raise error_cls(
            f"entrypoint {entrypoint!r} missing from files "
            f"({sorted(files.keys())!r})"
        )


def parse_probe_output(output: str) -> DeviceImplementation | None:
    """Extract a :class:`DeviceImplementation` from probe stdout.

    Scans for the ``__CHU_IMPL__:`` marker line emitted by
    :data:`PROBE_IMPLEMENTATION_SCRIPT` and ignores any surrounding
    output.  When an accompanying ``__CHU_UID__:`` line is present
    (new probe path), its hex payload is attached to
    :attr:`DeviceImplementation.uid`; output from older recordings
    that pre-date the UID line still parses cleanly with
    ``uid=""``.  Returns ``None`` when the ``__CHU_IMPL__:`` marker
    is missing or its payload is malformed — callers treat that as
    "probe unavailable" and fall back to per-device metadata from
    ``devices.yml``.

    Args:
        output: Combined stdout (and stderr if merged) from the probe
            script's ``execute`` call.
    """
    implementation_payload: str | None = None
    uid: str = ""
    for line in output.splitlines():
        if line.startswith("__CHU_IMPL__:"):
            implementation_payload = line[len("__CHU_IMPL__:"):]
        elif line.startswith("__CHU_UID__:"):
            uid = line[len("__CHU_UID__:"):].strip().upper()
    if implementation_payload is None:
        return None
    parts = implementation_payload.split("|", 2)
    if len(parts) != 3:
        return None
    name, version, machine = parts
    return DeviceImplementation(
        name=name.strip(),
        version=version.strip(),
        machine=machine.strip(),
        uid=uid,
    )


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

    def list_files_in_scope(self) -> list[str]:
        """Enumerate device files within the deploy's managed scope.

        Used by :meth:`Deployer.deploy_diff` to compute "what's on the
        device today that the next deploy would replace" — the
        difference becomes the *stale* set the diff routine deletes
        before writing the new payload.

        Returns paths in the same leading-slash form
        :meth:`deploy_files` accepts (``"/lib/foo.py"``,
        ``"/code.py"``, ``"/active.py"``, etc.).  Order is
        unspecified; callers sort if they need deterministic output.

        Transports that don't support persistent state (RAM-mode
        deploys: nothing survives across deploys to be diffed) return
        an empty list.  See ``plans/next-up.md`` "Replace multi-thing
        staging with scoped diff-deploy" for the design rationale.
        """
        ...

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the device's filesystem.

        No-op when *paths* is empty.  Each path must be in the same
        leading-slash form :meth:`deploy_files` accepts; transports
        normalise internally.  Missing paths are tolerated silently
        (the diff-routine call site is `delete what isn't in the new
        payload`, and a previous deploy may have already removed
        something — re-deleting shouldn't error).

        Best-effort: a single delete failure logs a warning but does
        not abort the batch.  The deploy that follows still writes
        the new payload — leaving a stale file in scope is preferable
        to skipping the deploy outright.
        """
        ...

    def wipe_filesystem(self) -> None:
        """Erase the device's user filesystem before the next deploy.

        Destructive — wipes *every* file the runtime can see, both
        in-scope (``/lib/*``, ``/code.py`` / ``/main.py`` / etc.) and
        out-of-scope (``/settings.toml``, hand-edited ``boot.py``,
        user-uploaded assets).  Used by ``chumicro-workspace deploy
        --wipe`` for clean-slate / corruption-recovery flows where
        an ordinary diff-deploy isn't enough.

        CircuitPython flash drives ``import storage;
        storage.erase_filesystem()`` over the raw REPL, which
        reformats the FAT volume and reboots the board — the
        transport swallows the connection-drop and re-establishes
        raw REPL afterwards.

        MicroPython walks ``/`` and removes every file + directory
        via ``os.remove`` / ``os.rmdir``.  Firmware partitions are
        untouched.

        RAM-mode / mount-mode deploys (CP RAM, MP mount) are no-ops
        — neither writes to flash, so there's nothing persistent to
        wipe.  Callers don't need to gate on mode; the transport
        does the right thing.

        Best-effort: per-file errors are tolerated silently so a
        transient I/O hiccup doesn't block the deploy that follows.
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
