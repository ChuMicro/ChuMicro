"""CircuitPython device transport using pyserial raw REPL.

Uses ``pyserial`` to connect to CircuitPython boards via serial and
execute code through raw REPL mode (Ctrl-A).  Two modes:

- **RAM mode** (default): All source code is sent inline through the
  raw REPL, with no file copy or flash writes required.
- **Flash mode**: Files are copied to the CIRCUITPY USB drive for
  persistent deployment.  Autoreload is managed via raw REPL commands.

Raw REPL protocol:
1. Ctrl-C × 2 interrupts any running code.
2. Ctrl-A enters raw REPL (prompt: ``raw REPL; CTRL-B to exit\\r\\n>``).
3. Send code bytes, terminated with Ctrl-D.
4. Response: ``OK<stdout>\\x04<stderr>\\x04>``.

"""

from __future__ import annotations

import shutil
import tempfile
import time as _time_module
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol, cast

from . import circuitpy_drive, flash_drive, source_minify
from ._line_dispatcher import StreamingLineDispatcher
from .circuitpython_bootstrap import build_circuitpython_deploy_scripts
from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    DeviceTransportError,
    MidDeployDisconnected,
    TimeSource,
    UnsupportedExtraFilesError,
    parse_probe_output,
    validate_entrypoint_in_files,
    write_files_to_staging,
)
from .runtime_marker import file_targets_runtime, is_test_support_module

_CTRL_A = b"\x01"
_CTRL_B = b"\x02"
_CTRL_C = b"\x03"
_CTRL_D = b"\x04"
_RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
_SOFT_REBOOT_MARKER = b"soft reboot"


class PostStageStep(Enum):
    """Which of the two post-rsync steps a deploy context runs: soft-
    reboot into the freshly-staged ``code.py``, or keep the live raw-
    REPL session for the harness to drive.

    Every context stages through the same clean-slate rsync +
    :data:`flash_drive.DEVICE_KEEP_SET`, so the bytes reach the board
    identically for a project, an example, and a functional test.
    Only the step taken once the bytes have landed differs, and only
    two values exist. Naming them here keeps the divergence explicit
    and gives the planned drift lint a symbol to anchor on instead of
    two unrelated methods that happen to differ.

    - :attr:`SOFT_REBOOT_AND_TAIL`: Ctrl-D soft-reboot so the board
      runs the freshly-staged ``code.py``, then capture its serial
      output.
    - :attr:`HARNESS_EXEC_OVER_REPL`: keep the live raw-REPL session
      alive (a soft-reboot would tear down state the harness drives
      over that session), refresh the FAT cache with a cheap directory
      walk, and let the caller exec the harness and collect asserts.

    The chosen value never changes how the bytes got there: everything
    up to and including the rsync runs the same code path.
    """

    SOFT_REBOOT_AND_TAIL = "soft-reboot then capture code.py output"
    HARNESS_EXEC_OVER_REPL = "keep raw-REPL session, exec harness, collect"

#: Default timeout in seconds for serial reads.
DEFAULT_TIMEOUT = 10.0

#: Idle timeout for ``execute()``, the bootstrap execution path.
#: Longer than ``DEFAULT_TIMEOUT`` because test bootstraps can include
#: silent CPU-bound work that outlasts the interactive-op default.
#: Short-running interactive ops (probe, autoreload, ``gc.collect``
#: between chunks) still use ``DEFAULT_TIMEOUT`` via
#: :meth:`_send_repl_command`.
_EXECUTE_IDLE_TIMEOUT = 60.0

#: Delay between Ctrl-C interrupts in seconds.
_INTERRUPT_DELAY = 0.1

#: Delay after entering raw REPL in seconds.
_ENTER_DELAY = 0.1

#: Poll budget for :meth:`_wait_for_board_to_see_entrypoint`.  See
#: that method for the USB-MSC sync rationale.
_BOARD_FILE_VISIBLE_POLL_ATTEMPTS = 20

#: Sleep between ``os.stat`` polls when waiting for a just-written
#: entrypoint to become visible to CP.
_BOARD_FILE_VISIBLE_POLL_INTERVAL = 0.25

#: Belt-and-suspenders settle after ``os.stat`` first reports the
#: expected size.  ``os.stat`` proves CP has seen the directory entry,
#: but in-flight block writes on the board side (flash program/erase,
#: FAT bookkeeping) can still be pending.  Sending Ctrl-D inside that
#: window risks a soft-reboot mid-write that macOS ``msdosfs`` defends
#: against by remounting the volume read-only.
_BOARD_FILE_VISIBLE_POST_SETTLE = 2.0

#: Initial settle delay before the first reconnect attempt after
#: ``storage.erase_filesystem()`` reboots the board.  CDC takes a
#: beat to come back, so wait this long before even starting to
#: poll for the port.
_WIPE_REBOOT_SETTLE_SECONDS = 2.0
#: Total wall-clock budget for the post-wipe reconnect.  A CP board
#: with a populated FAT volume can take several seconds to re-enumerate
#: after ``storage.erase_filesystem()`` reformats the volume, and a
#: stricter budget surfaces as a bare ``could not open port`` error
#: during a deploy the user reasonably expects to recover
#: transparently.
_WIPE_RECONNECT_TIMEOUT_SECONDS = 30.0
#: Poll interval between reconnect attempts inside
#: ``_WIPE_RECONNECT_TIMEOUT_SECONDS``.  Short enough to keep a
#: fast-back-up board's wipe latency under a second; long enough
#: not to flood the OS with port-open syscalls during the
#: reformat window.
_WIPE_RECONNECT_POLL_SECONDS = 0.5
#: Total wall-clock budget for the CIRCUITPY FAT volume to remount
#: after ``storage.erase_filesystem()``, measured from the moment
#: USB-CDC came back.  CDC and the FAT mount re-enumerate on
#: independent macOS timelines: CDC first, FAT typically a few
#: seconds later.  Without this wait, a ``deploy_files`` call
#: immediately after ``wipe_filesystem`` returns races the volume
#: mount and dies with "CIRCUITPY drive not found".  Short enough
#: that a genuinely unmounted drive (board ejected from Finder, USB
#: cable popped) surfaces quickly.
_WIPE_FAT_REMOUNT_TIMEOUT_SECONDS = 10.0


# The RAM-mode chunker reads gc.mem_free() on the board and sizes each
# inline script at half the free heap, clamped to this floor and ceiling.
_MIN_INLINE_SCRIPT_BUDGET_BYTES = 8 * 1024
_MAX_INLINE_SCRIPT_BUDGET_BYTES = 48 * 1024


def _walk_package_sources(
    source_directory: Path,
    *,
    target_runtime: str | None = None,
    include_test_support: bool = False,
) -> list[tuple[str, str]]:
    """Return every ``.py`` under packages rooted at *source_directory*.

    Only top-level children of *source_directory* that carry an
    ``__init__.py`` are treated as packages; other entries (README
    files, configuration, non-package directories) are skipped so
    RAM-mode payloads don't pick up files that aren't importable.

    Each returned entry is ``(dotted_module_name, source_text)``.
    Within a package, the ``__init__.py`` entry is emitted **after**
    every submodule so RAM-mode registration can resolve relative
    imports during the init block.

    When *target_runtime* is set, ``.py`` files carrying a
    ``__chumicro_runtimes__`` marker that doesn't match are skipped.
    """
    if not source_directory.is_dir():
        return []
    collected: list[tuple[str, str]] = []
    for package_directory in sorted(source_directory.iterdir()):
        if not package_directory.is_dir():
            continue
        init_file = package_directory / "__init__.py"
        if not init_file.exists():
            continue
        collected.extend(
            _walk_package_files(
                package_directory,
                package_directory.name,
                target_runtime=target_runtime,
                include_test_support=include_test_support,
            ),
        )
    return collected


def _walk_package_files(
    directory: Path,
    dotted_prefix: str,
    *,
    target_runtime: str | None = None,
    include_test_support: bool = False,
) -> list[tuple[str, str]]:
    """Return ``.py`` entries inside *directory* with ``__init__.py`` last."""
    collected: list[tuple[str, str]] = []
    init_entry: tuple[str, str] | None = None
    for child in sorted(directory.iterdir()):
        if child.is_dir():
            child_init = child / "__init__.py"
            if child_init.exists():
                collected.extend(
                    _walk_package_files(
                        child, f"{dotted_prefix}.{child.name}",
                        target_runtime=target_runtime,
                        include_test_support=include_test_support,
                    ),
                )
        elif child.suffix == ".py":
            if not file_targets_runtime(
                child, target_runtime=target_runtime,
            ):
                continue
            if is_test_support_module(child) and not include_test_support:
                # Test-support fakes are excluded unless the caller
                # explicitly opts in.
                continue
            source_text = child.read_text(encoding="utf-8")
            if child.name == "__init__.py":
                # Deferred, because the init block relies on submodules that
                # need to land in sys.modules first.
                init_entry = (dotted_prefix, source_text)
            else:
                module_name = f"{dotted_prefix}.{child.stem}"
                collected.append((module_name, source_text))
    if init_entry is not None:
        collected.append(init_entry)
    return collected


class SerialPort(Protocol):
    """Structural interface for a serial port.

    Implementations can satisfy this protocol without importing pyserial.
    """

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes, /) -> int | None: ...
    def close(self) -> None: ...
    def reset_input_buffer(self) -> None: ...


class CircuitpythonTransportError(DeviceTransportError):
    """Raised when a CircuitPython serial operation fails."""


class CircuitpythonMidDeployDisconnected(
    CircuitpythonTransportError, MidDeployDisconnected,
):
    """Raised when the device drops mid-deploy.

    The CircuitPython face of :class:`.protocol.MidDeployDisconnected`
    (which owns the message shape and the :attr:`cause` attribute).
    The wrapped :class:`OSError` is typically a
    :class:`serial.SerialException` here.
    """


class CircuitpythonTransport:
    """Transport for CircuitPython boards via pyserial raw REPL.

    Supports two modes:

    - **ram** (default): all source code is sent inline through the
      raw REPL, with no file copy or mounting needed.
    - **flash**: files are copied to the CIRCUITPY USB drive for
      persistent deployment.

    Args:
        address: Serial port path (e.g. ``/dev/cu.usbmodem14101``).
        baudrate: Serial baud rate.  Defaults to 115200.
        timeout: Read timeout in seconds.
        mode: ``"ram"`` (default) or ``"flash"``.
        serial_port_factory: Callable that creates a serial port object.
            Accepts ``(port, baudrate, timeout)`` keyword arguments.
            Defaults to ``serial.Serial``.  Inject a fake for testing.
        time: Object providing ``monotonic()`` and ``sleep()`` methods.
            Defaults to Python's ``time`` module.
            Inject ``FakeTime`` for deterministic tests with no
            wall-clock waits.

    The CIRCUITPY drive (``mode="flash"``) is auto-resolved at deploy
    time via :func:`_circuitpy_volume_candidates` and verified against
    the connected board's identity by :meth:`_verify_drive_for_board`.
    No per-transport drive path is stored.  Resolving by board UID at
    deploy time lets a host with two boards pick the right drive even
    when the OS gives the same mount name to a different board across
    reboots.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        timeout: float = DEFAULT_TIMEOUT,
        mode: str = "ram",
        serial_port_factory: Callable[..., object] | None = None,
        time: TimeSource | None = None,
        drive_scanner: Callable[[], list[Path]] | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self.mode = mode
        self._serial_port_factory: Callable[..., object] = (
            serial_port_factory or self._default_serial_factory
        )
        self._time: TimeSource = time or cast(TimeSource, _time_module)
        #: Callable returning candidate CIRCUITPY mount paths.  Defaults
        #: to :func:`circuitpy_drive._circuitpy_volume_candidates`.
        #: Injectable so callers can substitute a scanner that does not
        #: touch real OS mount tables.
        self._drive_scanner: Callable[[], list[Path]] = (
            drive_scanner
            if drive_scanner is not None
            else circuitpy_drive._circuitpy_volume_candidates
        )
        self._port: SerialPort | None = None
        #: One-time guard for the board-``settings.toml`` eviction
        #: notice, emitted at most once per transport instance even
        #: though a sweep may push many times.
        self._settings_eviction_notified = False
        self._staged_sources: list[tuple[str, str]] | None = None
        #: Set per :meth:`stage` call.  When ``True``, test-support
        #: fakes reach the board; default ``False`` excludes them.
        self._include_test_support: bool = False
        #: True once ``stage()`` or the RAM-mode ``deploy_files`` path
        #: has prepared the transport for ``execute()`` calls.  Kept
        #: separate from ``_staged_sources`` so the deploy path does
        #: not have to pretend it staged modules it did not collect.
        self._staged: bool = False
        #: The deployment target is CircuitPython, so files marked for
        #: another runtime via ``__chumicro_runtimes__`` are filtered out
        #: of every staging path (RAM mode + flash mode).
        self._target_runtime: str = "circuitpython"
        #: The :class:`PostStageStep` the last :meth:`_push_staging_to_drive`
        #: ran under.  Recorded so the single-staging-path invariant is
        #: assertable: both contexts issue the *identical* rsync and
        #: differ only in the named post-stage fork.
        self._post_stage_step: PostStageStep | None = None

    @staticmethod
    def _default_serial_factory(**kwargs) -> SerialPort:
        """Create a pyserial Serial port (default factory).

        ``exclusive=True`` requests POSIX ``TIOCEXCL`` on the underlying
        tty.  Without it, two host processes can both open the same
        ``/dev/cu.usbmodem...`` and interleave bytes on the same raw-REPL
        session: one process sees the other's prompt fragments, both
        surface as ``CircuitpythonTransportError`` tracebacks, and the
        board is left in an unknown state.  With it, the second open
        fails fast with ``EBUSY`` instead of silently corrupting both.
        """
        import serial
        return serial.Serial(**kwargs, exclusive=True)

    def connect(self) -> None:
        """Open the serial port and enter raw REPL mode.

        Sends Ctrl-C × 2 to interrupt any running code, then Ctrl-A
        to enter raw REPL.

        Raises:
            CircuitpythonTransportError: If the serial port cannot be
                opened or raw REPL prompt is not received.
        """
        try:
            self._port = cast(SerialPort, self._serial_port_factory(
                port=self.address,
                baudrate=self.baudrate,
                timeout=self.timeout,
            ))
        except Exception as open_error:
            raise CircuitpythonTransportError(
                f"Failed to open serial port {self.address}: {open_error}"
            ) from open_error

        self._enter_raw_repl()

    def _enter_raw_repl(self) -> None:
        """Interrupt running code and switch to raw REPL mode."""
        assert self._port is not None
        self._port.write(_CTRL_C)
        self._time.sleep(_INTERRUPT_DELAY)
        self._port.write(_CTRL_C)
        self._time.sleep(_INTERRUPT_DELAY)

        self._port.reset_input_buffer()

        self._port.write(_CTRL_A)
        self._time.sleep(_ENTER_DELAY)

        response = self._read_until(_RAW_REPL_PROMPT)
        if _RAW_REPL_PROMPT not in response:
            raise CircuitpythonTransportError(
                f"Did not receive raw REPL prompt.  Got: {response!r}"
            )

    def _disable_autoreload_before_drive_writes(self) -> None:
        """Send the autoreload-off REPL command.  Order-load-bearing.

        Every flash-mode path calls this immediately after
        :meth:`_enter_raw_repl` and before any host-side drive write.
        Otherwise the board's autoreload watcher sees the first file
        change, soft-reboots, the USB-CDC link re-enumerates, and the
        next host ``write()`` can hang in uninterruptible kernel I/O,
        the "wedged rsync".

        ``supervisor.runtime.autoreload`` is process-lifetime state, so
        a soft-reboot resets it to default-on; no explicit restore is
        needed.
        """
        self._send_repl_command(
            "import supervisor; supervisor.runtime.autoreload = False",
        )

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
        """Read source files into memory for inline execution.

        Sister of :meth:`deploy_files` that takes library/test/harness
        directories (``source_dirs`` + ``test_files`` + ``harness_source``)
        instead of a flat ``files: dict[device_path, bytes]``.

        In RAM mode, source code is read and stored for embedding into
        the bootstrap code block sent via raw REPL.

        In flash mode, source packages are copied to the CIRCUITPY USB
        drive after disabling autoreload.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage (stored for bootstrap
                generation).
            harness_source: Path to the test harness ``src/`` directory.
            extra_modules: Optional sibling Python files to register as
                importable on the device alongside library sources.
                In RAM mode they join ``staged_sources``; in flash mode
                they land at the drive root next to the test files.
            extra_files: Non-Python files to land at named device paths,
                typically ``{"/runtime_config.msgpack": <bytes>}`` so
                test code can call ``chumicro_config.load_runtime_config()``.
                **RAM mode raises** :class:`UnsupportedExtraFilesError`
                because there's no writable device-side filesystem to
                land bytes on; flash mode writes each file to the
                CIRCUITPY drive alongside library sources.

        Raises:
            UnsupportedExtraFilesError: ``mode == "ram"`` and
                *extra_files* is non-empty.  Switch the device's
                ``deploy_mode`` to ``"flash"`` to fix.
        """
        if extra_files and self.mode == "ram":
            raise UnsupportedExtraFilesError(
                "CircuitpythonTransport(mode='ram') cannot stage extra_files "
                f"({sorted(extra_files.keys())!r}): RAM mode bypasses the "
                "CIRCUITPY filesystem entirely.  Set the device's deploy_mode "
                "to 'flash' before staging tests that need a runtime_config "
                "or other on-device file.",
            )

        self._include_test_support = include_test_support
        self._staged_sources = []
        for source_directory in source_dirs:
            self._collect_package_sources(source_directory)
        self._collect_package_sources(harness_source)

        # Register sibling modules so the test source's top-level
        # `from _foo import ...` resolves when the inline bootstrap runs.
        if extra_modules:
            for module_path in extra_modules:
                self._staged_sources.append(
                    (module_path.stem, module_path.read_text(encoding="utf-8")),
                )

        if self.mode == "flash":
            self._stage_to_flash(
                source_dirs, test_files, harness_source,
                extra_modules=extra_modules,
                extra_files=extra_files,
            )
        self._staged = True

    def _verify_drive_for_board(self, drive_path: Path) -> Path:
        """Confirm *drive_path* is the CIRCUITPY mount for the connected board.

        Reads ``boot_out.txt`` on *drive_path* first so the
        single-board case skips the serial probe.  When the file is
        missing, delegates to :meth:`_identify_drive_via_probe`.
        Otherwise probes the board and matches its identity against
        the drive: UID is preferred (disambiguates two boards of the
        same model), and the machine string is the fallback for
        firmware that does not expose a UID.

        On a mismatch, every mounted ``CIRCUITPY*`` volume is scanned
        for one whose identity matches.  A found match is returned
        silently, so the "wrong mount came up first" case is
        self-correcting on macOS where mount order assigns
        ``CIRCUITPY`` and ``CIRCUITPY 1`` non-deterministically across
        multi-board hosts.  When nothing matches,
        :class:`CircuitpythonTransportError` is raised.
        """
        boot_uid, boot_machine = circuitpy_drive._read_boot_out_identity(drive_path)
        if boot_uid is None and boot_machine is None:
            # boot_out.txt missing on *drive_path*.  Probe the connected
            # board and scan candidate mounts for a boot_out.txt that
            # matches.  Raise if no candidate can be identified.
            # Silently falling back to *drive_path* would land the
            # deploy on whatever happened to be ``candidates[0]``,
            # which on a multi-CP-board host can be the wrong board.
            # Common trigger: the last deploy wiped boot_out.txt via
            # rsync --delete and the soft-reboot afterwards didn't
            # regenerate it (CP only writes boot_out.txt on hard
            # reset).
            return self._identify_drive_via_probe(drive_path)
        probe = self.probe_implementation()
        if probe is None:
            return self._drive_path_or_refuse_unverifiable(drive_path)
        if probe.uid and boot_uid is not None:
            return self._resolve_identity_match(
                drive_path,
                identity_label="UID",
                drive_identity=boot_uid,
                probe_identity=probe.uid,
                mount_finder=circuitpy_drive.find_circuitpy_drive_for_uid,
            )
        if probe.machine and boot_machine is not None:
            return self._resolve_identity_match(
                drive_path,
                identity_label="machine",
                drive_identity=boot_machine,
                probe_identity=probe.machine,
                mount_finder=circuitpy_drive.find_circuitpy_drive_for_machine,
            )
        return self._drive_path_or_refuse_unverifiable(drive_path)

    def _drive_path_or_refuse_unverifiable(self, drive_path: Path) -> Path:
        """Return *drive_path*, or refuse a wrong-board wipe when it can't be verified.

        Reached when the serial probe gave no identity to match the
        drive's ``boot_out.txt`` against.  Only a mount carrying a
        ``boot_out.txt`` counts as a real second board: a bare
        ``CIRCUITPY*`` directory is the stale placeholder macOS leaves
        after an unclean unmount, not another board, so it must not push
        the count into "ambiguous" and false-refuse a single-board
        deploy.  With two or
        more real boards, returning the drive that merely came up first
        could land the rsync --delete on the wrong one, so refuse and
        name the candidates instead.
        """
        real_boards = [
            mount
            for mount in circuitpy_drive._circuitpy_volume_candidates()
            if (mount / "boot_out.txt").is_file()
        ]
        if len(real_boards) > 1:
            listing = "\n".join(f"    {mount}" for mount in real_boards)
            raise CircuitpythonTransportError(
                f"cannot confirm {drive_path} is the connected board: the "
                f"serial probe returned no identity and more than one "
                f"CIRCUITPY* volume carries a boot_out.txt:\n{listing}\n"
                f"  Refusing rather than risk a wrong-board wipe.  Unplug "
                f"the other board(s), or replug / run "
                f"`chumicro-workspace reset-board --yes` to restore the "
                f"probe."
            )
        return drive_path

    def _identify_drive_via_probe(self, drive_path: Path) -> Path:
        """Find the right drive when *drive_path* has no boot_out.txt.

        Probes the connected board for its UID + machine string, then
        scans every mounted ``CIRCUITPY*`` volume's ``boot_out.txt``
        for a match.  Raises when the probe is unavailable or no
        candidate matches.  Silently returning *drive_path* would risk
        landing on the wrong board's mount on multi-CP-board hosts.
        """
        probe = self.probe_implementation()
        if probe is None or (not probe.uid and not probe.machine):
            raise CircuitpythonTransportError(
                f"CIRCUITPY drive at {drive_path} has no boot_out.txt "
                f"and the connected board did not provide an identity "
                f"probe.  Hard-reset the board (RESET button or "
                f"unplug/replug) to regenerate boot_out.txt, then retry."
            )
        candidate_identities = [
            (candidate, *circuitpy_drive._read_boot_out_identity(candidate))
            for candidate in self._drive_scanner()
        ]
        if probe.uid:
            target = probe.uid.upper()
            for candidate, uid, _machine in candidate_identities:
                if uid and uid == target:
                    return candidate
        if probe.machine:
            for candidate, _uid, machine in candidate_identities:
                if machine and machine == probe.machine:
                    return candidate
        identity = probe.uid or probe.machine
        raise CircuitpythonTransportError(
            f"CIRCUITPY drive at {drive_path} has no boot_out.txt and "
            f"no mounted CIRCUITPY* volume's boot_out.txt matches the "
            f"connected board (UID/machine={identity!r}).  Hard-reset "
            f"the board (RESET button or unplug/replug) to regenerate "
            f"boot_out.txt and retry."
        )

    def _resolve_identity_match(
        self,
        drive_path: Path,
        *,
        identity_label: str,
        drive_identity: str,
        probe_identity: str,
        mount_finder: Callable[[str], str | None],
    ) -> Path:
        """Compare drive ↔ board identity, then auto-correct or raise.

        ``identity_label`` is only used for the user-facing error
        message when no sibling mount matches.  Auto-correction on
        success is silent.  The corrected path is returned without
        host-side noise.
        """
        if drive_identity == probe_identity:
            return drive_path
        corrected = mount_finder(probe_identity)
        if corrected is None:
            raise CircuitpythonTransportError(
                f"CIRCUITPY drive at {drive_path} "
                f"({identity_label}={drive_identity!r}) does not match the "
                f"connected board ({identity_label}={probe_identity!r}), "
                f"and no other mounted CIRCUITPY* volume matches either.  "
                f"Confirm the board is plugged in and its CIRCUITPY drive "
                f"is mounted on the host."
            )
        return Path(corrected)

    def _resolve_circuitpy_drive(
        self, *, probe_writable: bool = False,
    ) -> Path:
        """Return a CIRCUITPY drive path, raising if none is usable.

        Scans every mounted ``CIRCUITPY*`` directory via
        :func:`_circuitpy_volume_candidates` and returns the first.
        Callers pair this with :meth:`_verify_drive_for_board` for
        the multi-board mount-order correction.

        *probe_writable* (default ``False``): when ``True``, additionally
        write+unlink a ``.chu-probe`` marker to confirm the mount is
        actually writable.  Required for polling a remount after
        ``storage.erase_filesystem()`` finishes, which needs an actual
        writability test.

        When left ``False``, the next rsync acts as its own write
        probe, and skipping the ``.chu-probe`` removes one host-side
        drive write before rsync starts (each write before rsync is a
        wedge-risk vector, since rsync to CIRCUITPY can hang in
        uninterruptible kernel I/O on macOS when the drive is wedged).
        When the drive is genuinely unwritable, the rsync subprocess
        surfaces the OS error in its stderr and ``flash_drive.rsync``
        wraps it as :class:`FlashDriveError`.
        """
        candidates = self._drive_scanner()
        if not candidates:
            raise CircuitpythonTransportError(
                "CIRCUITPY drive not found.  Connect the board's USB "
                "drive (or check that the host has it mounted)."
            )
        drive_path = candidates[0]
        # Belt-and-braces re-check.  ``_circuitpy_volume_candidates``
        # already filters by ``is_dir`` at scan time, but during a
        # FAT volume mid-remount the cached candidates list can name
        # a path that's temporarily ``is_dir() == False`` between the
        # scan and the next probe iteration.  Re-checking here turns
        # that into a clear "not mounted" error.
        if not drive_path.is_dir():
            raise CircuitpythonTransportError(
                f"CIRCUITPY drive not mounted: {drive_path}"
            )
        if probe_writable:
            probe = drive_path / ".chu-probe"
            try:
                probe.write_bytes(b"")
                probe.unlink()
            except OSError as error:
                raise CircuitpythonTransportError(
                    circuitpy_drive._format_probe_error(drive_path, error),
                ) from error
        return drive_path

    def _build_local_staging_tree(
        self,
        staging_path: Path,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
    ) -> None:
        """Mirror the desired drive layout inside a local staging directory.

        Library and harness packages go under ``lib/``.  Test files and
        sibling extra modules go at the root.  Binary ``extra_files``
        land at their declared device paths inside the staging tree,
        with leading slashes stripped and parents created on demand.
        Building locally is reliable (no FAT32 quirks), and only the
        rsync that follows has to deal with the device drive.  macOS
        extended attributes are stripped at the end so ``._`` resource
        forks don't end up on the FAT32 volume.

        ``__chumicro_runtimes__``-marked files for a different runtime
        are dropped at this stage.  The transport's own
        ``_target_runtime`` flows into ``merge_packages`` so the
        wrong-runtime adapters never reach flash.
        """
        lib_staging = staging_path / "lib"
        lib_staging.mkdir()
        for source_directory in source_dirs:
            flash_drive.merge_packages(
                source_directory, lib_staging,
                target_runtime=self._target_runtime,
                include_test_support=self._include_test_support,
            )
        flash_drive.merge_packages(
            harness_source, lib_staging,
            target_runtime=self._target_runtime,
            include_test_support=self._include_test_support,
        )

        for test_file in test_files:
            shutil.copy2(test_file, staging_path / test_file.name)

        if extra_modules:
            for module_path in extra_modules:
                shutil.copy2(module_path, staging_path / module_path.name)

        if extra_files:
            for device_path, content in extra_files.items():
                # Translate the leading-slash device path into a
                # relative path under the staging dir so the
                # subsequent rsync lands it at the matching device
                # location.  Empty / "/" / "/." path values are
                # nonsensical here, because a non-empty key with no
                # name component is a caller bug.
                relative = device_path.lstrip("/")
                if not relative:
                    raise CircuitpythonTransportError(
                        f"extra_files key {device_path!r} has no path "
                        "component; expected a leading-slash path like "
                        '"/runtime_config.msgpack"',
                    )
                target = staging_path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

        # Strip docstrings and comments from staged .py before the rsync so
        # libraries, tests, and the harness land as code only.
        source_minify.minify_python_tree(staging_path)
        flash_drive.strip_extended_attributes(staging_path)

    @staticmethod
    def _warn_if_flush_produced_empty_file(
        drive_path: Path, test_files: list[Path],
    ) -> None:
        """Probe the first test file after flush and warn on empty content.

        If the settle delay is too short, the drive returns stale or
        empty content and test runs silently pick up last session's
        code.  A warning here means ``flash_drive.FLUSH_SETTLE_DELAY``
        needs increasing for this board.
        """
        if not test_files:
            return
        probe_file = drive_path / test_files[0].name
        if not probe_file.exists():
            return
        if probe_file.read_bytes():
            return
        print(
            f"WARNING: {probe_file.name} is empty after flush: "
            f"FLUSH_SETTLE_DELAY "
            f"({flash_drive.FLUSH_SETTLE_DELAY}s) may be "
            f"too short for this board"
        )

    def _notice_settings_toml_eviction(self, drive_path: Path) -> None:
        """Loudly note, once, that a board ``settings.toml`` is being evicted.

        A clean deploy removes a board-resident ``settings.toml``
        because it is a competing wifi authority against chumicro's
        config-driven wifi (``runtime_config.msgpack`` merged from the
        host ``secrets.toml``).  That eviction is correct but
        invisible, and a user who hand-edited the CircuitPython-native
        ``settings.toml`` would otherwise lose it with no signal.
        Emit one prominent notice per transport instance (a sweep
        re-pushes many times, and the user needs to hear this once).
        """
        if self._settings_eviction_notified:
            return
        if not (drive_path / "settings.toml").is_file():
            return
        self._settings_eviction_notified = True
        print(
            "WARNING: removing the board's settings.toml.  chumicro "
            "drives wifi from the host-side secrets.toml "
            "(runtime_config.msgpack), and a board-resident "
            "settings.toml is a competing authority.  Put credentials "
            "in the workspace's secrets.toml, not on the board.",
        )

    def _push_staging_to_drive(
        self,
        staging_path: Path,
        *,
        rsync_delete: bool,
        post_stage: PostStageStep,
        rsync_additional_excludes: tuple[str, ...] = (),
        strip_xattrs: bool = False,
    ) -> Path:
        """Common drive-write phase.

        Once the local staging tree is built, the host-side work is
        identical regardless of how the tree was assembled: enter raw
        REPL, disable autoreload, resolve and verify the drive, plant
        macOS skip-sentinels into the staging tree, optionally strip
        xattrs, rsync, post-cleanup, flush.

        What happens after the rsync is named by the *post_stage*
        argument, a :class:`PostStageStep`.  Both values invalidate
        CP's in-RAM FAT cache so the rsynced
        files are visible.  The helper records the chosen step on
        ``self._post_stage_step`` so the "identical bytes path, named
        fork" invariant is assertable, and the post-stage action
        itself runs once this helper returns.

        Args:
            staging_path: Local staging directory whose contents are
                rsynced onto the drive.
            rsync_delete: ``--delete`` flag.  ``True`` means clean
                slate, only ``rsync_additional_excludes`` survives;
                ``False`` preserves drive files not in the staging tree.
            post_stage: Which :class:`PostStageStep` will run once this
                helper returns.  Recorded on
                ``self._post_stage_step``.  The post-stage action
                itself runs outside this helper (it needs session
                state).  The bytes-on-device path above it is
                identical regardless of this value.  That is the
                single-staging-path invariant.
            rsync_additional_excludes: Extra basenames to exclude.
                A clean push passes :data:`flash_drive.DEVICE_KEEP_SET`;
                additive deploys leave it empty.
            strip_xattrs: When ``True``, strip macOS extended
                attributes from the staging tree before rsync so
                AppleDouble ``._foo`` companions don't materialize on
                the FAT volume.

        Returns:
            The resolved drive path, for post-deploy work (e.g.
            polling for entrypoint visibility, warning if a flush left
            an empty marker).

        Raises:
            CircuitpythonTransportError: Drive can't be resolved /
                verified, or the rsync subprocess fails / times out.
        """
        # Record which fork the caller will run after this returns; the
        # body below is identical across contexts.
        self._post_stage_step = post_stage

        # ``_enter_raw_repl`` resends Ctrl-C / Ctrl-A on every call,
        # so repeated calls after ``connect()`` or an intervening
        # soft-reboot are safe.  Order across the two calls is
        # load-bearing; see :meth:`_disable_autoreload_before_drive_writes`.
        self._enter_raw_repl()
        self._disable_autoreload_before_drive_writes()
        drive_path = self._resolve_circuitpy_drive()
        drive_path = self._verify_drive_for_board(drive_path)

        if rsync_delete:
            self._notice_settings_toml_eviction(drive_path)

        flash_drive.plant_macos_sentinels_in_staging(staging_path)
        if strip_xattrs:
            flash_drive.strip_extended_attributes(staging_path)

        try:
            flash_drive.rsync(
                staging_path,
                drive_path,
                delete=rsync_delete,
                additional_excludes=rsync_additional_excludes,
            )
        except flash_drive.FlashDriveError as rsync_error:
            raise CircuitpythonTransportError(
                str(rsync_error),
            ) from rsync_error

        # Post-rsync cleanup of legacy noise dirs.  Only fires on
        # already-contaminated drives.  Once the sentinels prevent
        # re-creation, re-runs are a no-op.
        flash_drive.cleanup_macos_noise_dirs_post_rsync(drive_path)
        flash_drive.clean_dot_files(drive_path)
        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

        # Re-read every file via rsync --checksum --dry-run.  Any path
        # that comes back as "needs update" means the prior rsync's
        # writes did not commit.  Fail loudly here, before Ctrl-D
        # triggers a soft-reboot against an inconsistent FAT volume.
        try:
            divergent_paths = flash_drive.verify_rsync(
                staging_path,
                drive_path,
                additional_excludes=rsync_additional_excludes,
            )
        except flash_drive.FlashDriveError as verify_error:
            raise CircuitpythonTransportError(
                str(verify_error),
            ) from verify_error
        if divergent_paths:
            raise CircuitpythonTransportError(
                "Post-rsync verification found "
                f"{len(divergent_paths)} divergent file(s) on "
                f"{drive_path}: {divergent_paths!r}.  The first rsync's "
                "writes did not commit (FAT corruption, USB-MSC partial "
                "write, or the volume went read-only mid-deploy).  Tap "
                "RESET and re-deploy."
            )

        return drive_path

    def _stage_to_flash(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
    ) -> None:
        """Copy staged files to the CIRCUITPY USB drive via rsync.

        Builds a local staging directory that mirrors the desired drive
        layout (library and harness packages under ``lib/``, test
        files at the root), then rsyncs the whole project to the drive
        in one pass.  Building locally is reliable (no FAT32 quirks),
        and rsync handles the fragile USB-drive write.

        rsync flags:

        - ``--checksum``: verify content (FAT32 timestamps are
          unreliable).
        - ``--inplace``: write directly into files (avoids temp-file
          rename races on FAT32).
        - ``--delete``: remove stale files that no longer belong on
          the device.

        Rsync command line is a clean push (``--delete`` +
        ``additional_excludes=DEVICE_KEEP_SET``).  The staging tree
        carries libs + harness + ``test_*.py`` and no entrypoint,
        since the harness runs over the live raw REPL instead of
        booting ``code.py``.  A stale ``code.py`` is thus reconciled
        away like any non-keep-set file, which is what a test run
        wants.

        Disables autoreload before copying to prevent restarts during
        the file transfer.  Requires rsync on the host.

        Args:
            source_dirs: Library ``src/`` directories.
            test_files: Test files to deploy.
            harness_source: Path to the test harness ``src/`` directory.

        Raises:
            CircuitpythonTransportError: If the CIRCUITPY drive cannot
                be found or is not writable.
        """
        with tempfile.TemporaryDirectory() as staging_directory:
            staging_path = Path(staging_directory)
            self._build_local_staging_tree(
                staging_path, source_dirs, test_files, harness_source,
                extra_modules=extra_modules,
                extra_files=extra_files,
            )
            drive_path = self._push_staging_to_drive(
                staging_path,
                rsync_delete=True,
                post_stage=PostStageStep.HARNESS_EXEC_OVER_REPL,
                rsync_additional_excludes=flash_drive.DEVICE_KEEP_SET,
            )

        self._warn_if_flush_produced_empty_file(drive_path, test_files)
        # Refresh CP's FAT cache via a directory walk (cheap, and
        # preserves raw REPL session state, since a soft-reboot would tear
        # down the live session the harness drives test execution on).
        self._refresh_board_fat_cache_after_rsync()

    def _collect_package_sources(self, source_directory: Path) -> None:
        """Walk a source directory and extend ``_staged_sources``.

        Thin adaptor around :func:`_walk_package_sources` that keeps
        the transport's mutable state contained to this one method.
        Files marked for a runtime other than CircuitPython via
        ``__chumicro_runtimes__`` are filtered out.
        """
        assert self._staged_sources is not None
        self._staged_sources.extend(
            _walk_package_sources(
                source_directory, target_runtime=self._target_runtime,
                include_test_support=self._include_test_support,
            ),
        )

    def execute(
        self,
        bootstrap_script: str,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Send a code block through raw REPL and return captured stdout.

        Args:
            bootstrap_script: Python code to execute on the device.
            on_line: Optional callback invoked with each stdout line as
                it arrives over the serial link, before this method
                returns.  Lines are delivered without their trailing
                newline; ``\\r\\n`` is normalized to ``\\n``.  When
                ``None``, no streaming dispatch happens and the captured
                stdout is still returned in the usual request/response
                shape.

        Returns:
            Captured stdout from the device.

        Raises:
            CircuitpythonTransportError: If stage() has not been called,
                the device returns an error, or communication fails.
        """
        if not self._staged:
            raise CircuitpythonTransportError(
                "stage() must be called before execute()"
            )
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before execute()"
            )

        self._port.write(bootstrap_script.encode("utf-8"))
        self._port.write(_CTRL_D)

        # The raw REPL response framing is ``OK<stdout>\x04<stderr>\x04>``.
        # The streaming dispatcher skips the leading ``OK`` and stops at
        # the first ``\x04`` so callbacks only see stdout content.
        line_dispatcher = (
            StreamingLineDispatcher(
                on_line, prefix_bytes_to_skip=2, terminator=b"\x04",
            )
            if on_line is not None
            else None
        )
        raw_response = self._read_until(
            b"\x04>",
            idle_timeout=_EXECUTE_IDLE_TIMEOUT,
            on_chunk=line_dispatcher.feed if line_dispatcher is not None else None,
        )
        if line_dispatcher is not None:
            line_dispatcher.flush()

        return self._parse_raw_repl_response(raw_response)

    def execute_scripts(
        self,
        bootstrap_scripts: list[str],
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Execute multiple raw-REPL scripts in one interpreter session.

        Large CircuitPython RAM-mode payloads are more reliable when split into
        smaller scripts. Each script leaves the interpreter in raw REPL ready
        for the next chunk.

        Args:
            bootstrap_scripts: Ordered raw-REPL scripts to execute.
            on_line: Optional callback threaded through each per-script
                :meth:`execute` call.  Lines from all scripts are
                delivered in arrival order under a single callback.

        Returns:
            Stdout from the final script.
        """
        last_output = ""
        total_script_count = len(bootstrap_scripts)
        for script_index, bootstrap_script in enumerate(bootstrap_scripts, start=1):
            try:
                last_output = self.execute(bootstrap_script, on_line=on_line)
            except CircuitpythonTransportError as execute_error:
                raise CircuitpythonTransportError(
                    "CircuitPython inline bootstrap chunk "
                    f"{script_index}/{total_script_count} failed: {execute_error}"
                ) from execute_error

            if script_index != total_script_count:
                self._send_repl_command("import gc\ngc.collect()")

        return last_output

    def reset_into_bootloader(self) -> bool:
        """Reset into the UF2 bootloader via ``microcontroller`` module.

        ``microcontroller.on_next_reset(RunMode.BOOTLOADER)`` +
        ``microcontroller.reset()`` is CircuitPython's documented
        way to enter bootloader mode.  CP implements it across all
        ESP32-S2/S3/C6/P4 + RP2040/RP2350 + most SAMD/nRF52 ports,
        but whether the call actually puts a *particular* board in
        bootloader mode depends on that board's HAL build.  Treat
        success as observable, not declared: the raw-REPL link drops
        as the chip resets (expected), and a new bootloader port /
        UF2 drive becomes visible to whatever polls for one.  Don't
        add board-specific branching here.

        Closes the serial port directly so a subsequent
        :meth:`disconnect` becomes a no-op.  The USB link is gone on
        purpose and running the normal restore dance (``_enter_raw_repl``
        + autoreload-on + Ctrl-D) against a dying link only produces
        misleading warnings.
        """
        if self._port is None:
            return False
        try:
            self._send_repl_command(
                "import microcontroller\n"
                "microcontroller.on_next_reset("
                "microcontroller.RunMode.BOOTLOADER)\n"
                "microcontroller.reset()\n"
            )
        except Exception:
            pass
        try:
            self._port.close()
        except Exception:  # pragma: no cover -port is already dying
            pass
        self._port = None
        return True

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata.

        Uses the persistent raw REPL ``_send_repl_command`` helper so
        no staging is required.  ``sys.implementation`` is a built-in.
        Failures are swallowed (``None`` returned) so a flaky firmware
        never blocks the real test run.

        Returns:
            :class:`DeviceImplementation` on success, or ``None`` if
            the probe could not complete.
        """
        try:
            output = self._send_repl_command(PROBE_IMPLEMENTATION_SCRIPT)
        except Exception:  # pragma: no cover - hardware-only error paths
            return None
        return parse_probe_output(output)

    def probe_free_memory(self) -> int:
        """Return free heap bytes reported by the connected board."""
        output = self._send_repl_command("import gc\ngc.collect()\nprint(gc.mem_free())")
        memory_text = output.strip()
        try:
            return int(memory_text)
        except ValueError as parse_error:
            raise CircuitpythonTransportError(
                "CircuitPython free-memory probe returned unexpected output: "
                f"{memory_text!r}"
            ) from parse_error

    def inline_script_budget_bytes(self) -> int:
        """Return a conservative raw-REPL script budget based on live heap."""
        free_memory_bytes = self.probe_free_memory()
        if free_memory_bytes < _MIN_INLINE_SCRIPT_BUDGET_BYTES:
            raise CircuitpythonTransportError(
                "CircuitPython board reports too little free RAM for inline "
                f"execution ({free_memory_bytes} bytes available). Use flash "
                "deploy mode."
            )

        return min(
            _MAX_INLINE_SCRIPT_BUDGET_BYTES,
            max(_MIN_INLINE_SCRIPT_BUDGET_BYTES, free_memory_bytes // 2),
        )

    def run_script(self, script: str, *, timeout: float = 10.0) -> str:
        """Run *script* via the persistent raw REPL with no staging.

        Bypasses the ``stage()``-first precondition that
        :meth:`execute` enforces.  *script* must be self-contained
        (no imports of staged modules).

        Args:
            script: Self-contained Python source to run.
            timeout: Reserved for protocol parity; the underlying
                ``_send_repl_command`` uses its own deadline strategy.

        Returns:
            Captured stdout from the device.
        """
        del timeout  # underlying helper has its own deadline policy
        return self._send_repl_command(script)

    def soft_reset(self) -> None:
        """Soft-reset the interpreter and re-enter raw REPL.

        Exits raw REPL (Ctrl-B), sends Ctrl-D to trigger a soft reboot
        (which clears ``sys.modules`` and all interpreter state), waits
        for the reboot to complete, then re-enters raw REPL.

        Leaves the interpreter clean, with previous modules evicted
        from RAM.

        Raises:
            CircuitpythonTransportError: If raw REPL cannot be
                re-established after the reset.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "Cannot soft_reset: port is not open"
            )
        self._port.write(_CTRL_B)
        self._time.sleep(_ENTER_DELAY)
        self._port.write(_CTRL_D)
        self._time.sleep(0.5)
        self._port.reset_input_buffer()
        self._enter_raw_repl()

    def recover(self) -> None:
        """Attempt to recover raw REPL after a failed test.

        Sends Ctrl-C to interrupt any running code, drains stale
        output, then re-enters raw REPL mode.  Call this after a
        test error before running the next test.

        Raises:
            CircuitpythonTransportError: If raw REPL cannot be
                re-established.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "Cannot recover: port is not open"
            )
        self._enter_raw_repl()

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
        clean: bool = False,
    ) -> str:
        """Deploy *files* and execute *entrypoint* in the configured mode.

        In **flash mode**, every entry of *files* is written to the
        CIRCUITPY USB drive (auto-detecting the mount when not
        configured), the volume is flushed, and the entrypoint runs
        through the persistent raw REPL.  Autoreload is disabled
        during writes so the board does not reset mid-deploy.

        In **RAM mode**, no filesystem is touched.  Every
        non-entrypoint ``.py`` file is injected into ``sys.modules``
        via the class-as-module pattern (see
        :func:`build_circuitpython_deploy_scripts`) and the entrypoint
        runs as ``__main__``.  Non-``.py`` payload is silently skipped.

        Args:
            files: On-device-path -> bytes mapping.  In flash mode the
                leading slash is stripped before joining with the
                drive mount.  In RAM mode the path derives the dotted
                module name (``/lib/foo/bar.py`` -> ``foo.bar``).
            entrypoint: On-device path, must be a key of *files*.
            on_file_staged: Per-file callback after each write (flash
                mode) or before the inline scripts run (RAM mode, in
                sorted-key order).
            on_execute_line: Callback invoked once per captured output
                line, in order, after the entrypoint returns.
            tail_seconds: Flash mode only.  Override for how long
                serial output is captured after the soft-reboot.
                ``None`` uses :attr:`timeout`, ``0.0`` exits immediately
                without capturing.  RAM mode ignores this.
            clean: Flash mode only.  When ``True``, rsync ``--delete``
                prunes drive files outside the payload.

        Returns:
            Combined stdout from the entrypoint execution.

        Raises:
            CircuitpythonTransportError: Port not connected, entrypoint
                missing from *files*, or (flash mode) the CIRCUITPY
                drive cannot be located.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before deploy_files()"
            )
        validate_entrypoint_in_files(
            files, entrypoint, error_cls=CircuitpythonTransportError,
        )

        if self.mode == "ram":
            return self._deploy_files_ram(
                files,
                entrypoint,
                on_file_staged=on_file_staged,
                on_execute_line=on_execute_line,
            )

        try:
            with tempfile.TemporaryDirectory() as staging_directory:
                staging_path = Path(staging_directory)
                write_files_to_staging(staging_path, files, on_file_staged)
                # Strip docstrings and comments from every staged .py before
                # the push so the board carries code, not prose.  Capture the
                # entrypoint's post-strip byte size now, while the staging tree
                # still exists, because _wait_for_board_to_see_entrypoint polls
                # the drive for exactly that size after this temp dir is gone.
                source_minify.minify_python_tree(staging_path)
                entrypoint_staged = staging_path / entrypoint.lstrip("/")
                expected_entrypoint_size = entrypoint_staged.stat().st_size
                # clean=True: rsync --delete, only DEVICE_KEEP_SET survives.
                # clean=False: additive, drive files outside this payload persist.
                self._push_staging_to_drive(
                    staging_path,
                    rsync_delete=clean,
                    post_stage=PostStageStep.SOFT_REBOOT_AND_TAIL,
                    rsync_additional_excludes=(
                        flash_drive.DEVICE_KEEP_SET if clean else ()
                    ),
                    strip_xattrs=True,
                )
        except OSError as error:
            # The host-side staging-tree build can still hit OSError
            # (out of /tmp space, etc.).  Re-raise with the
            # ``_format_probe_error`` wrapper so the classifier routes
            # disk-full / RO to FLASH_COPY_FAILED instead of
            # CIRCUITPY_DRIVE_MISSING.  ``drive_path`` is set inside
            # the ``with`` only after the dict-walk succeeds, so this
            # handler covers both the dict-walk and any drive-resolve
            # failure that surfaces as an OSError.
            raise CircuitpythonTransportError(
                circuitpy_drive._format_probe_error("", error),
            ) from error

        self._wait_for_board_to_see_entrypoint(entrypoint, expected_entrypoint_size)

        # CP caches the FAT32 filesystem view in-memory; with autoreload
        # disabled, exec(open()) would read stale content.  Soft-reboot
        # from normal REPL so the board re-reads its filesystem and
        # runs the new code.py fresh.
        self._port.write(_CTRL_B)
        self._time.sleep(_ENTER_DELAY)
        self._port.write(_CTRL_D)
        output = self._read_code_py_output(tail_seconds=tail_seconds)

        # Do NOT re-enter raw REPL here.  That sends Ctrl-C and would
        # interrupt the entrypoint we just rebooted into.  ``disconnect``
        # tolerates either REPL state.

        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self, *, clean_slate: bool = False) -> list[str]:
        """Implements the contract on :meth:`TransportProtocol.list_files_in_scope`.

        Flash mode walks the CIRCUITPY USB drive directly via stdlib
        ``pathlib``, which is faster and simpler than a raw-REPL
        round-trip, and the drive's contents *are* the device's
        filesystem.  Pairs :meth:`_resolve_circuitpy_drive` with
        :meth:`_verify_drive_for_board` so the macOS multi-board
        mount-order swap is silently corrected to the connected
        board's actual mount before the walk.  RAM mode returns an
        empty list.
        """
        if self.mode != "flash":
            return []
        try:
            drive = self._resolve_circuitpy_drive()
            drive = self._verify_drive_for_board(drive)
        except CircuitpythonTransportError:
            return []
        return circuitpy_drive._list_scope_on_drive(
            drive, clean_slate=clean_slate,
        )

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the CIRCUITPY drive.

        Flash mode only.  RAM mode is a no-op since nothing was
        ever written to flash.  Each path is normalized to a
        leading-slash form, joined under the CIRCUITPY mount point,
        and unlinked best-effort.  Missing paths and per-path errors
        are tolerated silently so a transient I/O hiccup never blocks
        the deploy that follows.

        Pairs ``_resolve_circuitpy_drive`` with ``_verify_drive_for_board``
        so the macOS first-mount-wins behavior cannot unlink the
        *other* board's files on multi-board hosts.

        Uses :meth:`pathlib.Path.unlink` rather than rsync ``--delete``
        on purpose: rsync's delete semantics are "remove anything in
        DEST not in SRC", which is the wrong shape for "delete these
        specific files."  Unlink also dodges FAT32's data-write
        reliability concerns by only touching directory entries, no
        payload bytes.  The stale set is recomputed on every deploy,
        so a swallowed error here just retries next time.
        """
        if not paths or self.mode != "flash":
            return
        try:
            drive = self._resolve_circuitpy_drive()
            drive = self._verify_drive_for_board(drive)
        except CircuitpythonTransportError:
            return
        # If the delete set targets a stale board settings.toml, emit
        # the once-per-instance eviction notice here.  The guard fires
        # exactly once regardless of which removal path runs.
        if any(path.lstrip("/") == "settings.toml" for path in paths):
            self._notice_settings_toml_eviction(drive)
        for device_path in paths:
            relative = device_path.lstrip("/")
            target = drive / relative
            try:
                target.unlink()
            except (OSError, FileNotFoundError):  # pragma: no cover -best-effort
                pass
        # Reap empty directories across the whole drive scope.  unlink
        # removes files but not dirs, so a package whose every file
        # was stale leaves an empty `/<pkg>/` husk.  Two failure modes
        # the husk causes: (a) a stale `import <pkg>` fails *mid-
        # package* (dir present, __init__ gone) instead of cleanly;
        # (b) an empty `/<pkg>/` at the drive root resolves
        # `import <pkg>` to a PEP 420 namespace package and shadows
        # the populated `/lib/<pkg>/` deeper in `sys.path`.  The reap
        # sweeps the whole scope (not just this run's deletions) so
        # pre-existing husks clear too.
        # Bottom-up so nested husks collapse, and rmdir only removes
        # an *empty* dir, so a live package is never touched.
        # Dot-prefixed entries (macOS noise: ``.Spotlight-V100`` …) are
        # skipped: they're not ours to reap.  The drive root itself is
        # excluded by the ``rglob("*")`` starting point.
        directories = sorted(
            (
                entry for entry in drive.rglob("*")
                if entry.is_dir()
                and not any(
                    part.startswith(".")
                    for part in entry.relative_to(drive).parts
                )
            ),
            key=lambda candidate: len(candidate.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:  # pragma: no cover -non-empty or transient
                pass

    def clear_entrypoints(self) -> None:
        """Unlink ``code.py`` / ``main.py`` and confirm they are gone.

        Flash mode only.  RAM mode never writes a persistent
        entrypoint, so there is nothing to clear.  Host-side
        ``pathlib.unlink`` (a directory-entry-only op with no FAT data
        write), then ``flush_volume`` so the deletion is on the
        physical medium before a soft-reboot re-reads FAT, then a
        bounded poll that the drive no longer shows them.  Raises if
        an entrypoint is still present after the flush + poll budget,
        because a surviving ``code.py`` is exactly the soft-reboot race
        this removes.
        """
        if self.mode != "flash":
            return
        try:
            drive = self._resolve_circuitpy_drive()
            drive = self._verify_drive_for_board(drive)
        except CircuitpythonTransportError:
            # Drive not resolvable, so there is nothing we can (or
            # need to) clear.  The soft_reset path handles a missing
            # drive on its own.
            return
        targets = [drive / "code.py", drive / "main.py"]
        for target in targets:
            try:
                target.unlink()
            except (OSError, FileNotFoundError):  # already absent / hiccup
                pass
        flash_drive.flush_volume(drive, sleep=self._time.sleep)
        for _attempt in range(_BOARD_FILE_VISIBLE_POLL_ATTEMPTS):
            if not any(target.exists() for target in targets):
                return
            self._time.sleep(_BOARD_FILE_VISIBLE_POLL_INTERVAL)
        still_present = [
            target.name for target in targets if target.exists()
        ]
        if still_present:
            raise CircuitpythonTransportError(
                f"Could not clear stale entrypoint(s) {still_present} "
                f"from {drive} before reset.  A surviving code.py/main.py "
                "would run on the soft-reboot.  Tap RESET and retry, or "
                "reformat the drive (chumicro-workspace reset-board)."
            )

    def wipe_filesystem(self) -> None:
        """Implements the contract on :meth:`TransportProtocol.wipe_filesystem`.

        Drives the on-board nuclear option through raw REPL: the call
        reformats the FAT volume and reboots the board.  The host-side
        serial session goes away mid-call as USB-CDC drops, and the
        failure that surfaces is expected and swallowed.  After
        waiting for the reformat + reboot to settle the port is
        re-opened and raw REPL re-entered, leaving the transport in
        the same state :meth:`connect` does so a follow-up
        :meth:`deploy_files` works without further setup.
        """
        if self.mode != "flash":
            return
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before wipe_filesystem()",
            )
        try:
            self._send_repl_command(
                "import storage\nstorage.erase_filesystem()\n",
            )
        except Exception:  # noqa: BLE001 - reboot kills the REPL mid-call
            pass
        try:
            self._port.close()
        except Exception:  # pragma: no cover -port may already be torn down
            pass
        self._port = None
        # Settle, then poll-reconnect.  USB-CDC takes a beat to come
        # back after ``storage.erase_filesystem()`` reformats the
        # volume + reboots; on boards with a populated FAT it can be
        # several seconds before the host sees the device again.  A
        # one-shot connect after a fixed sleep races that window;
        # poll up to ``_WIPE_RECONNECT_TIMEOUT_SECONDS`` so a slower
        # board still recovers transparently.
        self._time.sleep(_WIPE_REBOOT_SETTLE_SECONDS)
        deadline = (
            self._time.monotonic() + _WIPE_RECONNECT_TIMEOUT_SECONDS
        )
        last_error: Exception | None = None
        while self._time.monotonic() < deadline:
            try:
                self.connect()
                break
            except CircuitpythonTransportError as connect_error:
                last_error = connect_error
                self._time.sleep(_WIPE_RECONNECT_POLL_SECONDS)
        else:
            raise CircuitpythonTransportError(
                f"Failed to reconnect to {self.address} within "
                f"{_WIPE_RECONNECT_TIMEOUT_SECONDS:.0f}s of "
                f"storage.erase_filesystem(); last error: {last_error}"
            )
        self._wait_for_circuitpy_remount()

    def _wait_for_circuitpy_remount(self) -> None:
        """Block until any CIRCUITPY FAT volume is usable post-wipe.

        ``storage.erase_filesystem()`` reboots the board, and USB-CDC
        and the FAT volume mount on independent macOS timelines:
        CDC first, FAT typically a few seconds later.  Waiting for
        CDC alone leaves two distinct host-side settle phases racing
        a follow-up deploy:

        1. Mount-not-yet-present: the configured drive path
           doesn't exist yet (FAT volume hasn't remounted at all).
        2. Mount-present-but-not-writable: the path is a directory
           but probe writes hit ``EACCES`` (macOS hasn't finished
           setting up access for the user).

        Both surface as deploy failures.  Polls
        :meth:`_resolve_circuitpy_drive` with ``probe_writable=True``
        so each iteration exercises both checks (``is_dir`` + tiny
        probe write/unlink) without duplicating the probe logic.  The
        poll waits for *any* CIRCUITPY mount to come back; the
        connected-board mount is selected on subsequent operations.
        """
        deadline = (
            self._time.monotonic() + _WIPE_FAT_REMOUNT_TIMEOUT_SECONDS
        )
        last_error: Exception | None = None
        while self._time.monotonic() < deadline:
            try:
                # probe_writable=True: this wait loop's whole purpose
                # is detecting when the drive becomes writable again
                # post-erase_filesystem.  ``is_dir()`` would lie during
                # the FAT-recreation window.
                self._resolve_circuitpy_drive(probe_writable=True)
                return
            except CircuitpythonTransportError as resolve_error:
                last_error = resolve_error
                self._time.sleep(_WIPE_RECONNECT_POLL_SECONDS)
        # Phrasing matches a recovery-classifier pattern so this
        # surfaces as CIRCUITPY_DRIVE_MISSING (which the classifier
        # promotes to MACOS_FSKIT_WEDGED when the wedge probe fires).
        # Don't reword without updating the matching pattern in
        # recovery.py.
        raise CircuitpythonTransportError(
            f"CIRCUITPY drive not mounted within "
            f"{_WIPE_FAT_REMOUNT_TIMEOUT_SECONDS:.0f}s of "
            f"storage.erase_filesystem(); last error: {last_error}"
        )

    def _deploy_files_ram(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None,
        on_execute_line: Callable[[str], None] | None,
    ) -> str:
        """RAM-mode branch of :meth:`deploy_files`.

        Uses :func:`build_circuitpython_deploy_scripts` to turn the
        ``files`` dict into an ordered list of raw-REPL scripts
        (helpers, stub registrations, module populations, entrypoint
        exec) and runs them through :meth:`execute_scripts`, which
        reuses the persistent raw-REPL session.  No CIRCUITPY drive
        or soft-reboot is involved.

        ``execute_scripts`` delegates to :meth:`execute`, whose guard
        ("``stage()`` must be called before ``execute()``") covers a
        different invariant.  Flips :attr:`_staged` directly so the
        guard passes without mutating :attr:`_staged_sources`, since
        the modules a deploy ships are not the same set
        :meth:`stage` collects.
        """
        if on_file_staged is not None:
            for device_path in sorted(files):
                on_file_staged(device_path)

        script_budget_bytes = self.inline_script_budget_bytes()
        deploy_scripts = build_circuitpython_deploy_scripts(
            files, entrypoint, max_chunk_size_bytes=script_budget_bytes,
        )
        self._staged = True
        output = self.execute_scripts(deploy_scripts)

        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def _refresh_board_fat_cache_after_rsync(self) -> None:
        """Force CP to re-scan FAT directory entries after a host rsync.

        CP caches the FAT directory layout in RAM.  An rsync that adds
        / removes / replaces files on the USB-MSC side updates the
        FAT on the device's flash, but the in-RAM cache may not pick
        up the new entries until something forces a directory read.
        Without this refresh, back-to-back rsyncs on the same board
        can hit ``ImportError: no module named X.Y`` because the
        freshly-rsynced module is on disk but invisible to CP's
        importer.

        Implementation: a recursive ``os.listdir`` walk from the FS
        root.  Listing a directory forces CP to re-read its FAT
        entries; walking covers nested package layouts (the typical
        ``/lib/<package>/<submodule>.py`` shape that the importer
        will hit next).

        Use this when the raw-REPL session must stay alive across the
        cache invalidation.  A Ctrl-D soft-reboot is the heavier
        alternative that tears down + rebuilds the entire CP runtime
        including its FAT cache.
        """
        # The walk script is small enough to inline.  ``S_IFDIR =
        # 0o40000 = 16384`` is stable across CP/MP and the stat[0]
        # bit-test is the cross-runtime portable way to detect a
        # directory entry.
        self._send_repl_command(
            "import os\n"
            "_seen = []\n"
            "def _walk(path):\n"
            "    if path in _seen: return\n"
            "    _seen.append(path)\n"
            "    try: entries = os.listdir(path)\n"
            "    except OSError: return\n"
            "    for entry in entries:\n"
            "        sub = path + entry if path.endswith('/') else path + '/' + entry\n"
            "        try:\n"
            "            mode = os.stat(sub)[0]\n"
            "            if mode & 16384:\n"
            "                _walk(sub)\n"
            "        except OSError: pass\n"
            "_walk('/')\n"
        )

    def _wait_for_board_to_see_entrypoint(
        self,
        entrypoint: str,
        expected_size: int,
    ) -> None:
        """Poll ``os.stat`` on the board until the entrypoint matches *expected_size*.

        Deterministic sync point that covers the gap between host-side
        ``sync`` + settle delay and CP actually seeing the USB-MSC
        write in its FatFs view.  Slower USB-CDC controllers finish
        the host-visible write before CP has processed all block-write
        callbacks, so the next soft-reboot can re-execute the previous
        file, and the capture is one cycle behind.

        Polls up to :data:`_BOARD_FILE_VISIBLE_POLL_ATTEMPTS` times with
        :data:`_BOARD_FILE_VISIBLE_POLL_INTERVAL` seconds between
        attempts, using the same raw-REPL session the caller is
        already holding.

        Raises:
            CircuitpythonTransportError: If the board never reports the
                expected size within the poll budget.
        """
        stat_command = (
            "import os\n"
            "try:\n"
            f"    print(os.stat({entrypoint!r})[6])\n"
            "except OSError:\n"
            "    print(-1)\n"
        )
        last_observed = "<no response>"
        for _ in range(_BOARD_FILE_VISIBLE_POLL_ATTEMPTS):
            response = self._send_repl_command(stat_command).strip()
            last_observed = response
            try:
                if int(response) == expected_size:
                    # Board has seen the directory entry; give any
                    # in-flight block writes / flash bookkeeping a
                    # moment to quiesce before we trigger the
                    # soft-reboot.
                    self._time.sleep(_BOARD_FILE_VISIBLE_POST_SETTLE)
                    return
            except ValueError:
                pass
            self._time.sleep(_BOARD_FILE_VISIBLE_POLL_INTERVAL)
        total_wait = (
            _BOARD_FILE_VISIBLE_POLL_ATTEMPTS
            * _BOARD_FILE_VISIBLE_POLL_INTERVAL
        )
        raise CircuitpythonTransportError(
            f"Board did not see {entrypoint!r} at {expected_size} bytes "
            f"within {total_wait:.1f}s (last reported size: "
            f"{last_observed!r}).  USB-MSC write may not have committed."
        )

    def _read_code_py_output(
        self, *, tail_seconds: float | None = None,
    ) -> str:
        """Read serial output from a fresh boot until code.py completes.

        CircuitPython prints ``soft reboot`` when the interpreter
        restarts (in response to Ctrl-D from the friendly REPL) and
        ``Code done running.`` when code.py returns (or raises).  The
        read synchronizes on ``soft reboot`` first so any pre-reboot
        bytes still in the host's serial buffer are discarded rather
        than mistaken for this cycle's output.

        For infinite-loop entrypoints the ``Code done running.`` marker
        never appears and the read times out, and callers receive the
        accumulated output up to that point.

        Args:
            tail_seconds: Override the read window.  ``None`` uses
                :attr:`timeout`.  ``0.0`` returns immediately without
                reading any bytes (caller wants to leave the board
                running and not block on capture).

        Returns:
            The portion of captured serial output between the
            ``code.py output:`` header and the ``Code done running.``
            marker (if present), or everything after ``soft reboot``
            otherwise.  When ``soft reboot`` is never observed the
            raw accumulated bytes are returned so callers can still
            diagnose the failure.
        """
        assert self._port is not None
        window = self.timeout if tail_seconds is None else tail_seconds
        if window <= 0.0:
            return ""
        done_marker = b"Code done running."
        accumulated = b""
        deadline = self._time.monotonic() + window
        soft_reboot_seen = False
        while self._time.monotonic() < deadline:
            waiting = self._port.in_waiting
            if waiting > 0:
                accumulated += self._port.read(waiting)
                if not soft_reboot_seen:
                    marker_index = accumulated.find(_SOFT_REBOOT_MARKER)
                    if marker_index != -1:
                        accumulated = accumulated[marker_index:]
                        soft_reboot_seen = True
                if soft_reboot_seen and done_marker in accumulated:
                    break
            else:
                self._time.sleep(0.01)
        return self._extract_code_output(accumulated)

    @staticmethod
    def _extract_code_output(raw_boot_output: bytes) -> str:
        """Extract the code.py portion from a fresh-boot serial capture.

        CircuitPython's boot banner + "Code done running." marker are
        stripped so callers see only the user code's output.  The
        boundary used is the "code.py output:" heading CP prints just
        before user output, with the trailing "Code done running."
        marker used as the end-of-output boundary.  When neither
        marker is present the raw text is returned so short-lived or
        untethered sessions still surface *something* useful.

        Args:
            raw_boot_output: Bytes captured between soft-reboot and
                the done marker (or timeout).
        """
        text = raw_boot_output.decode("utf-8", errors="replace")
        header_marker = "code.py output:"
        header_index = text.find(header_marker)
        if header_index != -1:
            trailing_newline = text.find("\n", header_index)
            if trailing_newline != -1:
                text = text[trailing_newline + 1:]
        for marker in ("Code done running.", "Press any key"):
            marker_index = text.find(marker)
            if marker_index != -1:
                text = text[:marker_index]
                break
        return text.strip("\r\n") + "\n"

    def disconnect(self) -> None:
        """Close the serial port and clear staged data.

        Pure teardown.  Sends a bare Ctrl-B (exits raw REPL when in
        raw REPL, a no-op control byte otherwise) so the next serial
        consumer never finds the board parked in raw REPL, then
        closes the port.  No Ctrl-C, because that would interrupt any
        ``code.py`` left running on the board.  No
        ``supervisor.runtime.autoreload = True``, because flipping
        autoreload back on outside an active raw-REPL session can layer
        an autoreload-driven soft-reboot on top of one already in
        flight, which can wedge ESP32-S2 USB-CDC firmware.

        Tolerates an already-closed port (e.g. after
        :meth:`reset_into_bootloader` nulled :attr:`_port`): the
        method finds nothing to close and only clears
        :attr:`_staged_sources`.
        """
        if self._port is not None:
            try:
                self._port.write(_CTRL_B)
                self._time.sleep(_ENTER_DELAY)
            except Exception as restore_error:
                print(f"WARNING: Failed to restore board state on disconnect: {restore_error}")
            try:
                self._port.close()
            except Exception as close_error:  # pragma: no cover
                print(f"WARNING: Failed to close serial port on disconnect: {close_error}")
            self._port = None
        self._staged_sources = None
        self._staged = False

    @property
    def staged_sources(self) -> list[tuple[str, str]] | None:
        """Return the staged module sources, or None if not staged."""
        return self._staged_sources

    def _read_until(
        self,
        marker: bytes,
        idle_timeout: float | None = None,
        *,
        on_chunk: Callable[[bytes], None] | None = None,
    ) -> bytes:
        """Read from serial until *marker* is found or the link goes silent.

        Uses an **idle timeout** rather than a wall-clock deadline: bytes
        arriving reset the clock, only *idle_timeout* seconds of
        consecutive silence end the wait.  Defaults to ``self.timeout``
        when ``None``.

        Per-call override exists because two workload classes share this
        primitive: short interactive ops (autoreload toggle,
        ``gc.mem_free`` probe) finish in <1 s, while bootstrap scripts
        can include silent CPU loops longer than that.  A longer
        ``idle_timeout`` keeps the parser from firing mid-script and
        raising "Malformed raw REPL response".

        Args:
            marker: Byte sequence to look for.
            idle_timeout: Seconds of consecutive silence that end the
                wait.  ``None`` means use ``self.timeout``.
            on_chunk: Optional callback invoked with each freshly-read
                byte chunk before it is appended to the accumulator.
                The hook is intentionally raw, so protocol-aware
                consumers (e.g. :meth:`execute`'s per-line dispatcher)
                wrap it with their own envelope-stripping logic.

        Returns:
            All bytes read, including the marker if found.  When the
            wait ends due to idle timeout, returns whatever accumulated.
        """
        assert self._port is not None
        effective_timeout = self.timeout if idle_timeout is None else idle_timeout
        accumulated = b""
        last_progress = self._time.monotonic()
        while self._time.monotonic() - last_progress < effective_timeout:
            waiting = self._port.in_waiting
            if waiting > 0:
                chunk = self._port.read(waiting)
                if on_chunk is not None:
                    on_chunk(chunk)
                accumulated += chunk
                last_progress = self._time.monotonic()
                if marker in accumulated:
                    return accumulated
            else:
                self._time.sleep(0.01)
        return accumulated

    def _send_repl_command(self, command: str) -> str:
        """Send a command through raw REPL and return stdout.

        The port must already be connected and in raw REPL mode.

        Args:
            command: Python code to execute.

        Returns:
            Captured stdout from the command.

        Raises:
            CircuitpythonTransportError: If the port is not connected
                or the command produces an error.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before sending REPL commands"
            )
        self._port.write(command.encode("utf-8"))
        self._port.write(_CTRL_D)
        raw_response = self._read_until(b"\x04>")
        return self._parse_raw_repl_response(raw_response)

    @staticmethod
    def _parse_raw_repl_response(raw_response: bytes) -> str:
        """Parse a raw REPL response into stdout text.

        Expected format: ``OK<stdout>\\x04<stderr>\\x04>``

        Args:
            raw_response: Raw bytes from the serial port.

        Returns:
            The stdout portion as a string.

        Raises:
            CircuitpythonTransportError: If the response is malformed
                or stderr contains error output.
        """
        response_text = raw_response.decode("utf-8", errors="replace")

        if not response_text.startswith("OK"):
            raise CircuitpythonTransportError(
                f"Raw REPL did not acknowledge code.  Response: {response_text!r}"
            )

        after_ok = response_text[2:]

        parts = after_ok.split("\x04")
        if len(parts) < 2:
            raise CircuitpythonTransportError(
                f"Malformed raw REPL response (missing \\x04 markers): "
                f"{response_text!r}"
            )

        stdout_text = parts[0]
        stderr_text = parts[1].rstrip(">").strip()

        if stderr_text:
            raise CircuitpythonTransportError(
                f"CircuitPython reported an error:\n{stderr_text}"
            )

        return stdout_text
