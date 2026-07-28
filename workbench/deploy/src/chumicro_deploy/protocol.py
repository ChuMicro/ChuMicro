"""Explicit transport protocol for ChuMicro device transports.

Captures the duck-typed transport contract that
:class:`CircuitpythonTransport` and :class:`MicropythonTransport`
both satisfy, in a form type checkers can enforce.

Two protocols are defined:

- :class:`TransportProtocol` is the minimum every transport must
  implement: ``connect``, ``stage``, ``execute``, ``soft_reset``,
  ``reset``, ``recover``, ``disconnect``.
- :class:`ExtendedTransportProtocol` adds the
  CircuitPython-specific RAM-mode chunking helpers
  (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).  ``MicropythonTransport`` does not
  need these, because there is no per-script RAM budget on mpremote.

CPython-only: these protocols ride on ``typing.Protocol``, which only
the workbench tooling uses (the cross-runtime device libraries that
satisfy the contract don't import this module).
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

    Populated by ``probe_implementation`` on transports that support
    it.  Identifies the runtime + board behind a connected device, and
    pins a UID that disambiguates two boards of the same model, so a
    mounted CIRCUITPY drive can be matched to its connected board
    without a mount-order-dependent path.

    Attributes:
        name: ``sys.implementation.name``, either ``"circuitpython"`` or
            ``"micropython"``.
        version: Dotted version from ``sys.implementation.version``
            (e.g. ``"10.1.4"`` or ``"1.26.0"``).
        machine: ``sys.implementation._machine`` on both runtimes,
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
#: - ``__CHU_IMPL__:name|version|machine``, parsed unchanged from its
#:   original three-field contract so a machine string that itself
#:   contains ``|`` (rare but legal) still round-trips intact.
#: - ``__CHU_UID__:<hex>``, emitted on a best-effort basis from
#:   ``microcontroller.cpu.uid`` (CircuitPython) or
#:   ``machine.unique_id()`` (MicroPython).  An empty value means the
#:   probe couldn't read a UID on this firmware.
#:
#: Uses only ``sys.implementation`` (present on both CP and MP) and
#: the UID modules above; needs no staged files and is safe to run
#: immediately after ``connect()``.
PROBE_IMPLEMENTATION_SCRIPT = (
    "import sys\n"
    # CircuitPython and MicroPython both ship a 4-tuple
    # ``(major, minor, micro, marker)`` from ``sys.implementation.version``,
    # where ``marker`` is ``''`` on a tagged build and ``'preview'`` on a
    # pre-release / dev build.  Slot 3 is a string in every shipped build,
    # so a ``[:3]`` slice keeps just the dotted ints and drops the marker.
    # Host CPython's 5-tuple ``(major, minor, micro, releaselevel, serial)``
    # also has ints in its first three slots, so the same slice works when
    # the unit tests exec the probe under a faked ``sys.implementation``.
    "_probe_version_str = '.'.join("
    "str(_part) for _part in sys.implementation.version[:3])\n"
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
    " + '|' + _probe_version_str"
    " + '|' + _probe_machine)\n"
    "print('__CHU_UID__:' + _probe_uid)\n"
)


#: Top-level on-device files chumicro-deploy treats as managed.
#: A diff-deploy that doesn't see one of these in the new payload
#: removes the existing copy from the device.  Outside-scope files
#: (user-uploaded images, hand-edited boot.py, etc.) are never
#: touched.
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

    Scope rule:

    * The four entrypoint / state files in :data:`DEPLOY_SCOPE_FILES`
      (``/code.py``, ``/main.py``, ``/active.py``,
      ``/runtime_config.msgpack``).
    * Everything under ``/lib/``; see :data:`DEPLOY_SCOPE_PREFIXES`.

    Anything else (user-uploaded images, manually-edited
    ``boot.py`` overrides, hand-tuned ``settings.toml`` knobs) is
    out of scope and survives every diff-deploy untouched.

    The check is path-shape only: callers should normalize their
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

    The exact message text (``"entrypoint <name> missing from
    files ..."``) is pattern-matched by
    :func:`~chumicro_deploy.recovery.classify_deploy_failure` to route
    to :attr:`DeployFailureKind.CONFIGURATION_ERROR`, so the message
    shape is part of the helper's contract.
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
    output.  When an accompanying ``__CHU_UID__:`` line is present,
    its hex payload is attached to :attr:`DeviceImplementation.uid`;
    output without that line parses cleanly with ``uid=""``.
    Returns ``None`` when the ``__CHU_IMPL__:`` marker is missing or
    its payload is malformed (the "probe unavailable" signal).

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


class UnsupportedExtraFilesError(NotImplementedError):
    """Raised when ``transport.stage(extra_files=...)`` can't be honored.

    Currently raised only by CircuitPython RAM mode: there is no
    writable device-side filesystem to land bytes on (RAM mode runs
    inline-execed source via raw REPL; CIRCUITPY is host-write but
    a host write while the device is running can trigger a soft reset
    that wipes the in-memory state).  Staging an on-device file
    artifact (typically ``runtime_config.msgpack`` for
    ``chumicro_config.load_runtime_config()``) requires flash mode.
    """


class TimeSource(Protocol):
    """Structural interface for an injectable time source.

    ``FakeTime`` from :mod:`chumicro_deploy.testing` is one conforming
    implementation that eliminates wall-clock waits.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class DeviceTransportError(Exception):
    """Base for both runtimes' transport errors.

    Orchestration that treats the transports uniformly (the
    ``RecoveringDeployer`` retry loop, the failure classifier)
    catches this instead of enumerating per-runtime subclasses, so
    adding a runtime doesn't mean auditing every catch site.
    """


class MidDeployDisconnected(DeviceTransportError):
    """Base for the per-runtime "device dropped mid-deploy" errors.

    A distinct branch so callers can ``except`` "the cable came out"
    without conflating it with other transport errors.  The original
    :class:`OSError` is attached as :attr:`cause` so callers that
    need the underlying errno can read it without re-parsing
    :func:`str` of the wrapper.
    """

    def __init__(self, cause: OSError, context: str = "") -> None:
        prefix = f"device disconnected during {context}" if context else (
            "device disconnected"
        )
        super().__init__(f"{prefix}: {cause}")
        self.cause = cause


def write_files_to_staging(
    staging_path: Path,
    files: Mapping[str, bytes],
    on_file_staged: Callable[[str], None] | None = None,
) -> None:
    """Write a device-path → bytes mapping into a host staging tree.

    The shared front half of both transports' ``deploy_files``:
    sorted for deterministic staging order, leading slashes stripped
    so the device-path → staging-path translation is reversible,
    parent dirs created on demand, per-file callback fired after each
    write.
    """
    for device_path in sorted(files):
        relative = device_path.lstrip("/")
        destination = staging_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files[device_path])
        if on_file_staged is not None:
            on_file_staged(device_path)


@runtime_checkable
class TransportProtocol(Protocol):
    """Minimum transport contract every device transport must satisfy."""

    #: User-facing deploy mode label.  ``"ram"`` / ``"flash"`` for
    #: CircuitPython, ``"mount"`` / ``"copy"`` for MicroPython.
    #: Drives per-library vs. bulk staging, soft-reset cadence, and
    #: inline vs. import bootstraps.
    mode: str

    def connect(self) -> None:
        """Verify the device is reachable."""
        ...

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
        include_test_support: bool = False,
    ) -> None:
        """Prepare the host-side staging area and (mode-dependent) push to device.

        *extra_modules* are additional Python files that the test files
        import as top-level modules.  Each is registered as importable
        on the device alongside library sources: in RAM mode they join
        ``staged_sources`` so the inline bootstrap registers them; in
        flash / copy / mount modes they land at the device root next
        to the test files.

        *extra_files* are non-Python files to land at named device paths.
        Keys are absolute device paths (``"/runtime_config.msgpack"``);
        values are the bytes to write.  Typical use is staging a
        ``runtime_config.msgpack`` alongside test files so on-device
        code can call :func:`chumicro_config.load_runtime_config`.
        Per-mode semantics: flash and copy modes write
        each file to the device's filesystem alongside library + test
        sources.  Mount mode writes to the host directory mounted as the
        device filesystem.  RAM mode raises
        :class:`UnsupportedExtraFilesError` because it has no writable
        device-side filesystem to land bytes on.
        """
        ...

    def execute(
        self,
        bootstrap_script: str,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Run *bootstrap_script* on the device and return captured stdout.

        When *on_line* is provided, each captured stdout line is
        dispatched to the callback as it arrives over the serial link,
        before :meth:`execute` returns.  Lines are dispatched without
        their trailing newline; ``\\r\\n`` is normalized to ``\\n``.
        When *on_line* is ``None`` (the default), behaviour is the
        request/response shape every existing call site assumes, and
        captured stdout still comes back as the return value.

        Streaming dispatch lets a host-side consumer react mid-execute:
        for example, a test fixture that opens a TCP connection only
        once the board prints a "server ready" line, or a long-running
        bake harness that surfaces board output as it lands instead of
        after the bootstrap finishes.
        """
        ...

    def run_script(self, script: str, *, timeout: float = 10.0) -> str:
        """Run *script* on the device without staging and return captured stdout.

        Sibling of :meth:`execute` for short, self-contained scripts
        that don't need any staged sources / test files / harness:
        e.g. a feature-detection probe (``try: import esp32`` etc.),
        a quick ``sys.implementation`` query, an inline diagnostic.
        Bypasses the ``stage()-must-be-called-first`` precondition
        that :meth:`execute` enforces.

        Args:
            script: Self-contained Python source to run via the raw
                REPL.  No imports of staged modules, only built-ins
                and runtime-provided modules.
            timeout: Idle-timeout for the script's output, in seconds.

        Returns:
            Captured stdout from the device.
        """
        ...

    def soft_reset(self) -> None:
        """Soft-reset the interpreter to clear modules and free heap."""
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

        Issues a runtime-specific reset command
        (``machine.bootloader()`` on MicroPython,
        ``microcontroller.on_next_reset(RunMode.BOOTLOADER)`` +
        ``microcontroller.reset()`` on CircuitPython) and swallows
        the connection-drop that follows.  The serial link is torn
        down as the board resets, so a clean response is not
        expected.

        Returns:
            ``True`` when the command was dispatched (the board
            should be rebooting into its bootloader).
            ``False`` when the runtime does not expose a
            bootloader-entry API, the transport could not be opened,
            or the command failed before reaching the board.
        """
        ...

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        **transport_kwargs: object,
    ) -> str:
        """Write files onto the device and execute the entrypoint.

        Distinct from :meth:`stage` + :meth:`execute`.  The former pair
        takes dirs + test files + harness source; this method takes a
        generic path-to-bytes map and a single entrypoint path.

        Args:
            files: On-device-path -> file-bytes mapping.  Paths may
                start with ``/``; transports normalize as needed.
            entrypoint: On-device path (must be a key of *files*) for
                the runtime to execute after staging.
            on_file_staged: Optional per-file callback invoked with
                the on-device path as each file is written.
            on_execute_line: Optional callback invoked once per line
                of captured execute output, in order.  Not guaranteed
                to stream live, since transports may call it after
                execute() completes.

        Returns:
            Combined stdout from the entrypoint execution.
        """
        ...

    def list_files_in_scope(self, *, clean_slate: bool = False) -> list[str]:
        """Enumerate device files within the deploy's managed scope.

        Returns the file set on the device today that the next deploy
        would replace.  Files in this set that aren't in the next
        deploy's payload are the *stale* set to delete before writing.

        ``clean_slate=True`` (the deploy default) widens the scope to
        the whole device minus the closed keep set
        (:data:`flash_drive.DEVICE_KEEP_SET`) and device-managed noise,
        so a stale board ``settings.toml`` or leftover user file is
        reconciled away.  ``clean_slate=False`` is the additive scope
        (the ``--no-wipe`` opt-out): only the entrypoint / state files
        and the library tree, leaving other root files in place.

        Returns paths in the same leading-slash form
        :meth:`deploy_files` accepts (``"/lib/foo.py"``,
        ``"/code.py"``, ``"/active.py"``, etc.).  Order is
        unspecified; callers sort if they need deterministic output.

        Transports that don't support persistent state (RAM-mode
        deploys: nothing survives across deploys to be diffed) return
        an empty list.
        """
        ...

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the device's filesystem.

        No-op when *paths* is empty.  Each path must be in the same
        leading-slash form :meth:`deploy_files` accepts; transports
        normalize internally.  Missing paths are tolerated silently:
        a previous deploy may have already removed something, so
        re-deleting shouldn't error.

        Best-effort: a single delete failure logs a warning but does
        not abort the batch.  The deploy that follows still writes
        the new payload, and leaving a stale file in scope is preferable
        to skipping the deploy outright.
        """
        ...

    def clear_entrypoints(self) -> None:
        """Delete any persisted ``code.py`` / ``main.py`` and confirm
        the deletion landed on the device before returning.

        Call once before a soft-reset when a stale entrypoint from a
        prior deploy would otherwise run on the reboot.  Filesystem
        transports unlink the files and verify they are gone, flushing
        FAT first on CIRCUITPY so the bytes hit the medium before the
        reboot re-reads it.  RAM and mount transports never persist
        an entrypoint, so this is a no-op there.
        """
        ...

    def wipe_filesystem(self) -> None:
        """Erase the device's user filesystem before the next deploy.

        Destructive: wipes *every* file the runtime can see, both
        in-scope (``/lib/*``, ``/code.py`` / ``/main.py`` / etc.) and
        out-of-scope (``/settings.toml``, hand-edited ``boot.py``,
        user-uploaded assets).  Use for clean-slate / corruption-
        recovery flows where an ordinary diff-deploy isn't enough,
        and to reclaim flash filled with stage residue that has hit
        ``ENOSPC`` mid-deploy.

        Per-runtime recipe matrix:

        - **CircuitPython** (any board): ``import storage;
          storage.erase_filesystem()`` over the raw REPL.  Reformats
          the FAT volume and triggers a hard reset; the transport
          swallows the USB-CDC drop and re-establishes raw REPL after
          the volume re-mounts.
        - **MicroPython on rp2** (Pi Pico W et al.): ``os.umount('/');
          os.VfsLfs2.mkfs(rp2.Flash()); machine.soft_reset()``.
        - **MicroPython on esp32** (Lolin S2 family et al.):
          ``os.umount('/'); os.VfsLfs2.mkfs(esp32.Partition.find(
          TYPE_DATA, label='vfs')[0]); machine.soft_reset()``.
        - Other MicroPython substrates: raise ``RuntimeError`` until
          a verified recipe is added.

        ``mkfs`` is required for MicroPython rather than a recursive
        ``os.remove`` walk: LittleFS metadata + wear-leveling
        artifacts survive a file-by-file delete, so a board with a
        small partition (rp2's ~850 KB, esp32's 2 MB) can still hit
        ``ENOSPC`` mid-deploy after a non-mkfs "wipe."  Firmware
        partitions are untouched on every runtime.

        RAM-mode / mount-mode deploys (CP RAM, MP mount) are no-ops,
        since neither writes to flash, so there's nothing persistent
        to wipe.  No need to gate on mode at the call site.
        """
        ...


@runtime_checkable
class ExtendedTransportProtocol(TransportProtocol, Protocol):
    """Transport contract plus the CircuitPython RAM-mode chunking helpers.

    Implemented by :class:`CircuitpythonTransport`.  Runtime-check
    against this protocol before calling the chunked-execute helpers.
    """

    #: Module sources captured by ``stage()`` for RAM-mode inline
    #: execution.  Each entry is ``(dotted_module_name, source_text)``.
    #: ``None`` before ``stage()`` has been called.
    staged_sources: list[tuple[str, str]] | None

    def execute_scripts(
        self,
        bootstrap_scripts: list[str],
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Run multiple bootstrap scripts in one interpreter session.

        *on_line* threads through each per-script
        :meth:`TransportProtocol.execute` call, so a chunked CP RAM-mode
        deploy dispatches stdout lines across all scripts in arrival
        order under a single callback.
        """
        ...

    def probe_free_memory(self) -> int:
        """Return free heap bytes reported by the connected board."""
        ...

    def inline_script_budget_bytes(self) -> int:
        """Return a conservative per-script budget based on live free heap."""
        ...
