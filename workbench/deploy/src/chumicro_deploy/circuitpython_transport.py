"""CircuitPython device transport using pyserial raw REPL.

Uses ``pyserial`` to connect to CircuitPython boards via serial and
execute code through raw REPL mode (Ctrl-A).  Two modes:

- **RAM mode** (default): All source code is sent inline through the
  raw REPL — no file copy or flash writes required.
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
from pathlib import Path
from typing import Protocol, cast

from . import circuitpy_drive, flash_drive
from .circuitpython_bootstrap import build_circuitpython_deploy_scripts
from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    UnsupportedExtraFilesError,
    parse_probe_output,
    validate_entrypoint_in_files,
)
from .runtime_marker import file_targets_runtime, is_test_support_module

_CTRL_A = b"\x01"
_CTRL_B = b"\x02"
_CTRL_C = b"\x03"
_CTRL_D = b"\x04"
_RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
_SOFT_REBOOT_MARKER = b"soft reboot"

#: Default timeout in seconds for serial reads.
DEFAULT_TIMEOUT = 10.0

#: Idle timeout for ``execute()`` — the test-bootstrap execution path.
#: Longer than ``DEFAULT_TIMEOUT`` because test bootstraps can include
#: silent CPU-bound work (the fragmentation-test histogram bisection
#: does ~7,500 ``bytearray`` allocs at the 256-byte tier on a Lolin S2's
#: 2 MB heap) that can outlast the interactive-op default.  Short-running
#: interactive ops (probe, autoreload, ``gc.collect`` between chunks)
#: still use ``DEFAULT_TIMEOUT`` via :meth:`_send_repl_command`.
_EXECUTE_IDLE_TIMEOUT = 60.0

#: Delay between Ctrl-C interrupts in seconds.
_INTERRUPT_DELAY = 0.1

#: Delay after entering raw REPL in seconds.
_ENTER_DELAY = 0.1

#: How many times to poll the board's view of a just-written entrypoint
#: before giving up.  USB MSC writes can trail the host-side ``sync`` +
#: settle delay on slower controllers (observed on Pi Pico W), and
#: soft-rebooting before CP sees the new blocks produces a one-cycle-
#: delayed capture (the previous ``code.py`` runs again against the
#: cached FAT view).  Polling ``os.stat`` via raw REPL gives us a
#: deterministic sync point.
_BOARD_FILE_VISIBLE_POLL_ATTEMPTS = 20

#: Sleep between ``os.stat`` polls when waiting for a just-written
#: entrypoint to become visible to CP (see
#: :data:`_BOARD_FILE_VISIBLE_POLL_ATTEMPTS`).
_BOARD_FILE_VISIBLE_POLL_INTERVAL = 0.25

#: Belt-and-suspenders settle after ``os.stat`` first reports the
#: expected size.  ``os.stat`` proves CP has seen the directory entry,
#: but in-flight block writes on the board side (flash program/erase,
#: FAT bookkeeping) can still be pending; sending Ctrl-D inside that
#: window risks a soft-reboot mid-write that macOS ``msdosfs`` defends
#: against by remounting the volume read-only.
_BOARD_FILE_VISIBLE_POST_SETTLE = 2.0

#: Seconds to wait after ``storage.erase_filesystem()`` before
#: Initial settle delay before the first reconnect attempt after
#: ``storage.erase_filesystem()`` reboots the board.  CDC takes a
#: beat to come back; this is the minimum we wait before even
#: starting to poll for the port.
_WIPE_REBOOT_SETTLE_SECONDS = 2.0
#: Total wall-clock budget for the post-wipe reconnect.  CP boards
#: with a populated FAT volume occasionally take 6-10 seconds to
#: re-enumerate after ``storage.erase_filesystem()`` reformats the
#: volume — a stricter budget surfaces as a bare ``could not open
#: port`` error during a deploy that the user reasonably expects
#: to recover transparently.  Empirically determined against the
#: four-board canonical matrix (`.scratch/wipe_soak.py`).
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
#: independent macOS timelines — CDC first, FAT typically a few
#: seconds later.  Without this wait, a ``deploy_files`` call
#: immediately after ``wipe_filesystem`` returns races the volume
#: mount and dies with "CIRCUITPY drive not found".  10 s is well
#: above empirical FAT-remount latency on the four-board canonical
#: matrix while staying short enough that a genuinely unmounted
#: drive (board ejected from Finder, USB cable popped) surfaces
#: quickly.
_WIPE_FAT_REMOUNT_TIMEOUT_SECONDS = 10.0


# RAM-mode inline scripts are chunked based on live free-heap measurements.
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
                # Test-support fakes never ship to a product/app/
                # functional deploy; only the on-device unit sweep
                # passes include_test_support=True.
                continue
            source_text = child.read_text(encoding="utf-8")
            if child.name == "__init__.py":
                # Deferred — the init block relies on submodules that
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

    Matches the subset of ``serial.Serial`` used by the transport.
    Fakes in tests satisfy this protocol without importing pyserial.
    """

    @property
    def in_waiting(self) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes, /) -> int | None: ...
    def close(self) -> None: ...
    def reset_input_buffer(self) -> None: ...


class TimeSource(Protocol):
    """Structural interface for an injectable time source.

    Matches the subset of Python's ``time`` module used by the transport.
    ``FakeTime`` from :mod:`chumicro_deploy.testing` satisfies this
    protocol so tests can eliminate wall-clock waits.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class CircuitpythonTransportError(Exception):
    """Raised when a CircuitPython serial operation fails."""


class CircuitpythonMidDeployDisconnected(CircuitpythonTransportError):
    """Raised when the device drops mid-deploy.

    Subclass so callers can ``except`` "the cable came out" without
    conflating it with other transport errors (raw-REPL stuck,
    bootstrap exec failed, drive missing).  Mirrors
    :class:`chumicro_repl.session.ReplSessionDisconnected`.

    The original :class:`OSError` (typically
    :class:`serial.SerialException`) is attached as :attr:`cause`
    so callers that need the underlying errno or message can read
    it without re-parsing the wrapper's own ``str(error)``.
    """

    def __init__(self, cause: OSError, context: str = "") -> None:
        prefix = f"device disconnected during {context}" if context else (
            "device disconnected"
        )
        super().__init__(f"{prefix}: {cause}")
        self.cause = cause


class CircuitpythonTransport:
    """Transport for CircuitPython boards via pyserial raw REPL.

    Supports two modes:

    - **ram** (default): all source code is sent inline through the
      raw REPL — no file copy or mounting needed.
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
    No per-transport drive path is stored — multi-board hosts get the
    correct mount picked from the board's UID rather than from a
    pinned-at-registration-time path that mount-order can invalidate.
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
        #: Tests inject a fake scanner to avoid touching real OS mount
        #: tables; the chumicro_deploy.testing.isolate_from_host_filesystem
        #: helper continues to work as a module-level fallback for tests
        #: that don't construct their own transport.
        self._drive_scanner: Callable[[], list[Path]] = (
            drive_scanner
            if drive_scanner is not None
            else circuitpy_drive._circuitpy_volume_candidates
        )
        self._port: SerialPort | None = None
        self._staged_sources: list[tuple[str, str]] | None = None
        #: Set per :meth:`stage` call.  Only the on-device unit sweep
        #: (``--target device-unit``) passes ``True`` so test-support
        #: fakes reach the board; every product/app/functional deploy
        #: leaves it ``False``.
        self._include_test_support: bool = False
        #: True once ``stage()`` or the RAM-mode ``deploy_files`` path
        #: has prepared the transport for ``execute()`` calls.  Kept
        #: separate from ``_staged_sources`` so the deploy path does
        #: not have to pretend it staged modules it did not collect.
        self._staged: bool = False
        #: The transport's identity *is* its target runtime.  Selecting
        #: :class:`CircuitpythonTransport` means the deployment target
        #: is CircuitPython, so files marked for another runtime via
        #: ``__chumicro_runtimes__`` are filtered out of every staging
        #: path (RAM mode + flash mode).
        self._target_runtime: str = "circuitpython"

    @staticmethod
    def _default_serial_factory(**kwargs) -> SerialPort:  # pragma: no cover
        """Create a pyserial Serial port (default factory)."""
        import serial
        return serial.Serial(**kwargs)

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
        # Ctrl-C × 2 to interrupt any running program.
        self._port.write(_CTRL_C)
        self._time.sleep(_INTERRUPT_DELAY)
        self._port.write(_CTRL_C)
        self._time.sleep(_INTERRUPT_DELAY)

        # Drain any pending output before entering raw REPL.
        self._port.reset_input_buffer()

        # Ctrl-A to enter raw REPL.
        self._port.write(_CTRL_A)
        self._time.sleep(_ENTER_DELAY)

        # Read until we see the raw REPL prompt.
        response = self._read_until(_RAW_REPL_PROMPT)
        if _RAW_REPL_PROMPT not in response:
            raise CircuitpythonTransportError(
                f"Did not receive raw REPL prompt.  Got: {response!r}"
            )

    def _disable_autoreload_before_drive_writes(self) -> None:
        """Send the autoreload-off REPL command — order-load-bearing.

        Every flash-mode entry point (``_stage_to_flash``,
        ``deploy_files``) calls this **immediately** after
        :meth:`_enter_raw_repl` and **before** any host-side drive
        operation — ``.chu-probe``, ``neuter_macos_metadata`` sentinels,
        the rsync itself.  Otherwise the board's autoreload watcher
        sees the first file change, schedules a soft-reboot, the
        USB-CDC link re-enumerates, and the next host-side ``write()``
        may land in uninterruptible kernel I/O wait — the "wedged
        rsync" failure mode (rsync to CIRCUITPY can hang in
        uninterruptible kernel I/O).

        ``supervisor.runtime.autoreload`` is process-lifetime state on
        the CP VM, so any soft-reboot resets it back to default-on —
        no explicit restore is needed on either flash-mode path:

        * ``deploy_files`` issues an explicit Ctrl-D between rsync and
          ``code.py`` capture; that reboot restores the default.
        * ``_stage_to_flash`` runs harness code via the live raw REPL
          session and does not reboot inside the session.  The board
          is left with autoreload off until the next reset / power
          cycle, which is fine because functional-test sessions don't
          need ``code.py``-style reload-on-edit behavior, and the
          next flash-mode entry point will re-disable anyway.
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

        **Test-harness API.**  Sister of :meth:`deploy_files` for the
        functional-test orchestrator (`source_dirs` + `test_files` +
        `harness_source` are test-runner concepts).  Production
        deploys use :meth:`deploy_files` with a flat
        ``files: dict[device_path, bytes]`` instead.

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
            extra_files: Non-Python files to land at named device paths
                — typically ``{"/runtime_config.msgpack": <bytes>}`` so
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
                f"({sorted(extra_files.keys())!r}) — RAM mode bypasses the "
                "CIRCUITPY filesystem entirely.  Set the device's deploy_mode "
                "to 'flash' before staging tests that need a runtime_config "
                "or other on-device file.",
            )

        self._include_test_support = include_test_support
        self._staged_sources = []
        # Collect library package sources (needed for both modes).
        for source_directory in source_dirs:
            self._collect_package_sources(source_directory)
        # Collect harness sources.
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

        macOS assigns ``/Volumes/CIRCUITPY`` / ``/Volumes/CIRCUITPY 1``
        in mount order, so :func:`_circuitpy_volume_candidates`'s first
        entry may belong to a different board on multi-board hosts.
        This method probes the connected board and compares its
        identity against ``boot_out.txt`` on *drive_path*:

        1. **UID** (``microcontroller.cpu.uid`` ↔ ``UID:...`` line
           in ``boot_out.txt``) is preferred — it disambiguates two
           boards of the same model.
        2. **machine string** (``sys.implementation._machine`` ↔
           ``...; <machine>`` suffix on line 1) is the fallback for
           older firmware whose probe or ``boot_out.txt`` doesn't
           expose a UID.

        On a mismatch, every mounted ``CIRCUITPY*`` volume is scanned
        for one whose identity matches; the match wins silently —
        the wrong-mount-came-up-first case is auto-corrected without
        host-side noise.  When no match is found a
        :class:`CircuitpythonTransportError` is raised that asks the
        user to confirm the board is plugged in and the right
        CIRCUITPY drive is mounted.

        When ``boot_out.txt`` is missing on *drive_path* (e.g. after a
        clean rsync that didn't exclude it, or before the first hard
        reboot of a freshly-formatted drive), the method probes the
        connected board and scans sibling mounts for one whose
        ``boot_out.txt`` matches.  When no candidate can be
        identified, the method raises rather than silently returning
        *drive_path* — a fall-open in that state risks landing the
        deploy on the wrong board's mount on multi-CP-board hosts.

        ``boot_out.txt`` is checked first so the serial-probe
        roundtrip is skipped entirely when the identity already
        matches the connected board (the common single-board case).
        """
        boot_uid, boot_machine = circuitpy_drive._read_boot_out_identity(drive_path)
        if boot_uid is None and boot_machine is None:
            # boot_out.txt missing on *drive_path*.  Probe the connected
            # board and scan candidate mounts for a boot_out.txt that
            # matches.  Raise if no candidate can be identified —
            # silently falling back to *drive_path* would land the
            # deploy on whatever happened to be ``candidates[0]``,
            # which on a multi-CP-board host can be the wrong board.
            # Common trigger: the last deploy wiped boot_out.txt via
            # rsync --delete and the soft-reboot afterwards didn't
            # regenerate it (CP only writes boot_out.txt on hard
            # reset).
            return self._identify_drive_via_probe(drive_path)
        probe = self.probe_implementation()
        if probe is None:
            return drive_path
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
        return drive_path

    def _identify_drive_via_probe(self, drive_path: Path) -> Path:
        """Find the right drive when *drive_path* has no boot_out.txt.

        Sister of :meth:`_resolve_identity_match` for the no-identity-
        on-drive case.  Probes the connected board for its UID +
        machine string, then scans every mounted ``CIRCUITPY*``
        volume's ``boot_out.txt`` for a match.  Raises when the probe
        is unavailable or no candidate matches — silently returning
        *drive_path* would risk landing on the wrong board's mount.

        Reads each ``boot_out.txt`` exactly once into a
        ``(path, uid, machine)`` list and matches both fields
        in-memory — the UID and machine probes target the same files
        on the same FAT volumes, so reading twice (one per probe)
        would double the disk I/O on the auto-correct path.
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
        """Compare drive ↔ board identity; auto-correct or raise.

        Extracted helper so the UID and machine-string branches of
        :meth:`_verify_drive_for_board` share their compare-and-fix
        logic.  ``identity_label`` is only used for the user-facing
        error message when no sibling mount matches.  Auto-correction
        on success is silent — the corrected path is returned and the
        caller proceeds without host-side noise.
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
        :func:`_circuitpy_volume_candidates` and returns the first.  On
        multi-board hosts that first pick may not be the one belonging
        to *this* transport — callers pair this with
        :meth:`_verify_drive_for_board`, which probes the connected
        board and silently swaps to the UID-matching mount when the
        first pick is for the wrong board.

        *probe_writable* (default ``False``) — when ``True``, additionally
        write+unlink a ``.chu-probe`` marker to confirm the mount is
        actually writable.  Only the wipe-and-wait path
        (:meth:`_wait_for_writable_drive_after_wipe`) uses this — it
        polls until ``storage.erase_filesystem()`` finishes and the
        FAT remounts cleanly, which requires actually testing
        writability.

        Normal staging / deploy paths leave it ``False``: the rsync
        that follows is itself a write probe, and skipping the
        ``.chu-probe`` removes one host-side drive write before rsync
        starts (each write before rsync is a wedge-risk vector —
        rsync to CIRCUITPY can hang in uninterruptible kernel I/O on
        macOS when the drive is wedged).  When
        the drive is genuinely unwritable, the rsync subprocess
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
        # already filters by ``is_dir`` at scan time, but the wipe-and-
        # wait path re-resolves while the FAT volume is mid-remount —
        # the cached candidates list can name a path that's
        # temporarily ``is_dir() == False`` between the scan and the
        # next probe iteration.  Re-checking here turns that into a
        # clear "not mounted" error the wait loop can recognize.
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

        Library and harness packages go under ``lib/``; test files and
        sibling extra modules go at the root.  Binary ``extra_files``
        land at their declared device paths inside the staging tree —
        leading slashes stripped, parents created on demand.  Building
        locally is reliable (no FAT32 quirks) — only the rsync that
        follows has to deal with the device drive.  macOS extended
        attributes are stripped at the end so ``._`` resource forks
        don't end up on the FAT32 volume.

        ``__chumicro_runtimes__``-marked files for a different runtime
        are dropped at this stage — the transport's own
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
                # nonsensical here — a non-empty key with no name
                # component is a caller bug.
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
            f"WARNING: {probe_file.name} is empty after flush — "
            f"FLUSH_SETTLE_DELAY "
            f"({flash_drive.FLUSH_SETTLE_DELAY}s) may be "
            f"too short for this board"
        )

    def _push_staging_to_drive(
        self,
        staging_path: Path,
        *,
        rsync_delete: bool,
        rsync_additional_excludes: tuple[str, ...] = (),
        strip_xattrs: bool = False,
    ) -> Path:
        """Common drive-write phase shared by ``_stage_to_flash`` (functional
        tests) and ``deploy_files`` (production deploy).

        Both callers build their staging tree differently — functional
        tests assemble it from package source directories + harness +
        test files; production deploys take a flat ``{path: bytes}``
        dict — but once the local tree is built, the host-side work is
        identical: enter raw REPL, disable autoreload, resolve and
        verify the drive, plant macOS skip-sentinels into the staging
        tree, optionally strip xattrs, rsync, post-cleanup, flush.

        Caller-specific concerns kept out of this helper:

        * **Building the staging tree.**  Functional tests use
          :meth:`_build_local_staging_tree`; ``deploy_files`` walks the
          flat file dict.  This split is the legitimate difference
          between the two call paths.
        * **What happens after the rsync.**  ``_stage_to_flash`` does a
          cheap directory-walk FAT-cache refresh (the harness expects
          the raw-REPL session to stay alive); ``deploy_files`` does a
          full soft-reboot via Ctrl-D (it's about to run code.py
          anyway).  Both invalidate CP's in-RAM FAT cache so the
          freshly-rsynced files are visible to the importer; the
          choice of mechanism is caller-driven.

        Args:
            staging_path: Local staging directory whose contents are
                rsynced onto the drive.
            rsync_delete: ``--delete`` flag.  Functional tests pass
                ``True`` (clean slate between test files); production
                deploys pass ``False`` (preserve user data not in the
                file map).
            rsync_additional_excludes: Extra basenames to exclude.
                Functional tests pass ``FUNCTIONAL_TEST_EXTRA_EXCLUDES``
                (boot.py, code.py, settings.toml — preserved across
                runs); production deploys leave empty.
            strip_xattrs: When ``True``, strip macOS extended
                attributes from the staging tree before rsync.
                Production deploys want this so AppleDouble ``._foo``
                companions don't materialize on the FAT volume; the
                functional-test path skips it because the staging
                tree is built from source files that already passed
                through ``shutil.copytree`` (no xattrs survive).

        Returns:
            The resolved drive path, for callers that need it for
            their post-deploy work (e.g. polling for entrypoint
            visibility, warning if a flush left an empty marker).

        Raises:
            CircuitpythonTransportError: Drive can't be resolved /
                verified, or the rsync subprocess fails / times out.
        """
        # Order is load-bearing.  Enter raw REPL FIRST + disable
        # autoreload BEFORE any host-side drive write — otherwise
        # rsync to CIRCUITPY can hang in uninterruptible kernel I/O.
        # ``_enter_raw_repl`` is idempotent (resends Ctrl-C / Ctrl-A)
        # so the second call from ``deploy_files`` after ``connect()``
        # is safe; ``_stage_to_flash`` benefits because its caller
        # (the pytest-device session cache) may have soft-rebooted
        # the board between batches.
        self._enter_raw_repl()
        self._disable_autoreload_before_drive_writes()
        drive_path = self._resolve_circuitpy_drive()
        drive_path = self._verify_drive_for_board(drive_path)

        # macOS skip-sentinels go into the staging tree so they ride
        # along in the rsync — not as separate on-drive writes that
        # would compound the wedge risk.
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

        # Post-rsync cleanup of legacy noise dirs — only fires on
        # already-contaminated drives; idempotent once the sentinels
        # have prevented re-creation.
        flash_drive.cleanup_macos_noise_dirs_post_rsync(drive_path)
        # Strip macOS AppleDouble (._foo) companions before flushing.
        flash_drive.clean_dot_files(drive_path)
        # Flush the volume so the device reads current content.
        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

        # Re-read every file via rsync --checksum --dry-run.  Any path
        # that comes back as "needs update" means the prior rsync's
        # writes did not commit — fail loudly here, before Ctrl-D
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
        layout — library and harness packages under ``lib/``, test
        files at the root — then rsyncs the whole project to the drive
        in one pass.  Building locally is reliable (no FAT32 quirks);
        rsync handles the fragile USB-drive write.

        rsync flags:

        - ``--checksum``: verify content (FAT32 timestamps are
          unreliable).
        - ``--inplace``: write directly into files (avoids temp-file
          rename races on FAT32).
        - ``--delete``: remove stale files that no longer belong on
          the device.

        Device config files (``boot.py``, ``boot_out.txt``,
        ``settings.toml``) are excluded from deletion so they
        survive the sync.

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
                rsync_additional_excludes=flash_drive.FUNCTIONAL_TEST_EXTRA_EXCLUDES,
            )

        self._warn_if_flush_produced_empty_file(drive_path, test_files)
        # Stage path: refresh CP's FAT cache via a directory walk
        # (cheap, preserves raw REPL session state).  ``deploy_files``
        # uses a soft-reboot for the same purpose because it has to
        # boot into code.py anyway; here the harness drives test
        # execution via the live raw REPL session, so a soft-reboot
        # would tear down state the harness expects.
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

    def execute(self, bootstrap_script: str) -> str:
        """Send a code block through raw REPL and return captured stdout.

        Args:
            bootstrap_script: Python code to execute on the device.

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

        # Send the code.
        self._port.write(bootstrap_script.encode("utf-8"))
        # Ctrl-D to execute.
        self._port.write(_CTRL_D)

        # Read the response.  Raw REPL format:
        # OK<stdout>\x04<stderr>\x04>
        # Use a longer idle timeout: test-bootstrap scripts can include
        # silent CPU-bound work (e.g. fragmentation-test histogram
        # bisection on Lolin S2) that exceeds DEFAULT_TIMEOUT — see
        # _EXECUTE_IDLE_TIMEOUT.
        raw_response = self._read_until(
            b"\x04>", idle_timeout=_EXECUTE_IDLE_TIMEOUT,
        )

        return self._parse_raw_repl_response(raw_response)

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Execute multiple raw-REPL scripts in one interpreter session.

        Large CircuitPython RAM-mode payloads are more reliable when split into
        smaller scripts. Each script leaves the interpreter in raw REPL ready
        for the next chunk.

        Args:
            bootstrap_scripts: Ordered raw-REPL scripts to execute.

        Returns:
            Stdout from the final script.
        """
        last_output = ""
        total_script_count = len(bootstrap_scripts)
        for script_index, bootstrap_script in enumerate(bootstrap_scripts, start=1):
            try:
                last_output = self.execute(bootstrap_script)
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
        ESP32-S2/S3/C6/P4 + RP2040/RP2350 + most SAMD/nRF52 ports —
        but whether the call actually puts a *particular* board in
        bootloader mode depends on that board's HAL build.  Treat
        success as observable, not declared: the raw-REPL link
        drops as the chip resets (expected), and a new bootloader
        port / UF2 drive shows up for the caller's drive-poll to
        spot.  Don't add board-specific branching here; if the
        poll comes up empty, the manual-entry fallback handles it.

        Closes the serial port directly so a subsequent
        :meth:`disconnect` becomes a no-op — the USB link is gone on
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
        except Exception:  # pragma: no cover — port is already dying
            pass
        self._port = None
        return True

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata.

        Uses the persistent raw REPL ``_send_repl_command`` helper so
        no staging is required — ``sys.implementation`` is a built-in.
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

        Mirrors :meth:`probe_implementation`'s use of
        :meth:`_send_repl_command` — bypasses the
        ``stage()``-first precondition that :meth:`execute` enforces.
        *script* must be self-contained (no imports of staged
        modules).

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

        Use between test groups to ensure each group starts with a
        clean interpreter — previous modules are evicted from RAM.

        Raises:
            CircuitpythonTransportError: If raw REPL cannot be
                re-established after the reset.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "Cannot soft_reset — port is not open"
            )
        # Exit raw REPL → normal REPL.
        self._port.write(_CTRL_B)
        self._time.sleep(_ENTER_DELAY)
        # Ctrl-D in normal REPL triggers soft reboot.
        self._port.write(_CTRL_D)
        self._time.sleep(0.5)
        # Drain the soft-reboot banner.
        self._port.reset_input_buffer()
        # Re-enter raw REPL for the next test group.
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
                "Cannot recover — port is not open"
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

        **Production deploy API.**  Sister of :meth:`stage` (test-
        harness use only).  Takes a flat ``files: dict[device_path,
        bytes]`` rather than `source_dirs` + `test_files` so it
        composes cleanly with arbitrary :class:`FileSource`
        implementations (`DirectorySource`, `FileMapSource`,
        `ImportGraphSource`, workspace-shaped sources).  The CLI's
        ``chumicro-deploy deploy`` and `Deployer.deploy` /
        `deploy_diff` both route here.

        Flash mode writes every entry of *files* to the CIRCUITPY USB
        drive (auto-detecting the mount path when not configured),
        flushes the volume, then execs the entrypoint through the
        persistent raw REPL.  Autoreload is disabled during writes so
        the board does not reset mid-deploy.

        RAM mode skips the filesystem entirely: every non-entrypoint
        ``.py`` file is injected into ``sys.modules`` via the
        class-as-module pattern (see
        :func:`build_circuitpython_deploy_scripts`), then the
        entrypoint runs as ``__main__``.  No CIRCUITPY drive is
        required.  Non-``.py`` payload is silently skipped — callers
        that need to ship assets must use flash mode.

        Args:
            files: On-device-path -> bytes mapping.  In flash mode the
                leading slash is stripped before joining with the drive
                mount point; in RAM mode the path is used to derive
                the dotted module name (``/lib/foo/bar.py`` ->
                ``foo.bar``).
            entrypoint: On-device path (must be a key of *files*).
            on_file_staged: Per-file callback invoked after each file
                is written to the drive (flash mode) or before the
                inline scripts run (RAM mode, in sorted-key order so
                tests get a deterministic sequence).
            on_execute_line: Callback invoked once per line of captured
                output (in order) after the entrypoint returns.
            tail_seconds: Override for how long flash mode captures
                serial output after the soft-reboot.  ``None`` (default)
                uses :attr:`timeout`.  Set higher when the entrypoint's
                first ``print`` lands beyond the default window (e.g.
                MQTT connect, blocking ``recv``); set to ``0.0`` to
                exit immediately after triggering Ctrl-D and leave the
                board running without capturing any output.  RAM mode
                ignores this — its execution path is synchronous.

        Returns:
            Combined stdout from the entrypoint execution.

        Raises:
            CircuitpythonTransportError: The port is not connected,
                the entrypoint is missing from *files*, or (flash
                mode) the CIRCUITPY drive cannot be located.
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
                for device_path in sorted(files.keys()):
                    relative = device_path.lstrip("/")
                    staging_destination = staging_path / relative
                    staging_destination.parent.mkdir(parents=True, exist_ok=True)
                    staging_destination.write_bytes(files[device_path])
                    if on_file_staged is not None:
                        on_file_staged(device_path)
                # ``clean=True`` (e.g. ``deploy-example``) tells rsync
                # to delete drive files not in the staging tree so each
                # demo lands clean.  Three files are excluded from the
                # wipe so the next deploy + the device stay healthy:
                #
                # * ``settings.toml`` — user runtime config.
                # * ``boot.py`` — user custom boot logic.
                # * ``boot_out.txt`` — CP writes this only on *hard*
                #   reboot (deploy soft-reboots via Ctrl-D, which
                #   doesn't regenerate it).  Wiping it strands the
                #   drive without identity info until the next power
                #   cycle, which breaks
                #   :meth:`_verify_drive_for_board`'s UID match on
                #   the next deploy — the deploy then "fails open" to
                #   ``_circuitpy_volume_candidates()[0]`` and can land
                #   on the wrong board's drive on multi-board hosts.
                #
                # ``clean=False`` (the default; the ``chumicro-workspace
                # deploy`` shape) preserves every drive file outside
                # the new payload — appropriate when users hand-install
                # lib/ deps via circup and only the current import
                # graph rotates per deploy.
                self._push_staging_to_drive(
                    staging_path,
                    rsync_delete=clean,
                    rsync_additional_excludes=(
                        ("settings.toml", "boot.py", "boot_out.txt")
                        if clean else ()
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

        # Wait for the board to see the new entrypoint before soft-
        # rebooting.  Without this check, a slower USB-MSC controller
        # (Pi Pico W) can report "write complete" on the host side
        # while CP's FatFs view is still the previous run's, so the
        # soft-reboot re-executes the stale file and the captured
        # output is one cycle behind the deploy.
        self._wait_for_board_to_see_entrypoint(entrypoint, len(files[entrypoint]))

        # CP caches the FAT32 filesystem view in-memory; with autoreload
        # disabled, exec(open()) would read stale content.  Soft-reboot
        # from normal REPL so the board re-reads its filesystem and
        # runs the new code.py fresh.
        self._port.write(_CTRL_B)  # exit raw REPL
        self._time.sleep(_ENTER_DELAY)
        self._port.write(_CTRL_D)  # trigger soft-reboot
        output = self._read_code_py_output(tail_seconds=tail_seconds)

        # Do NOT re-enter raw REPL here — that sends Ctrl-C and would
        # interrupt the entrypoint we just rebooted into.  ``disconnect``
        # tolerates either REPL state.

        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self) -> list[str]:
        """List on-device files within the deploy's managed scope.

        Flash mode walks the CIRCUITPY USB drive directly via stdlib
        ``pathlib`` — faster + simpler than a raw-REPL round-trip,
        and the drive's contents *are* the device's filesystem.

        Pairs ``_resolve_circuitpy_drive`` with ``_verify_drive_for_board``
        so the macOS multi-board mount-order swap is silently corrected
        to the connected board's actual mount before the walk — without
        verify, the diff layer reads the *other* board's files and
        reports zero stale entries when there's a real diff to apply.

        RAM mode returns an empty list — RAM-mode deploys never
        touch flash, so there's nothing persistent to diff between
        deploys.
        """
        if self.mode != "flash":
            return []
        try:
            drive = self._resolve_circuitpy_drive()
            drive = self._verify_drive_for_board(drive)
        except CircuitpythonTransportError:
            return []
        return circuitpy_drive._list_scope_on_drive(drive)

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the CIRCUITPY drive.

        Flash mode only — RAM mode is a no-op since nothing was
        ever written to flash.  Each path is normalized to a
        leading-slash form, joined under the CIRCUITPY mount point,
        and unlinked best-effort.  Missing paths and per-path errors
        are tolerated silently so a transient I/O hiccup never blocks
        the deploy that follows.

        Pairs ``_resolve_circuitpy_drive`` with ``_verify_drive_for_board``
        for the same reason ``list_files_in_scope`` does — without
        verify, the macOS first-mount-wins behavior could unlink the
        *other* board's files (this is the destructive sister of the
        list-the-wrong-drive bug).

        Uses :meth:`pathlib.Path.unlink` rather than rsync ``--delete``
        on purpose: rsync's delete semantics are "remove anything in
        DEST not in SRC" — wrong shape for "delete these specific
        files."  Unlink also dodges FAT32's data-write reliability
        concerns by only touching directory entries, no payload
        bytes.  The diff layer recomputes the stale set
        on every deploy, so a swallowed error here just retries
        next time.
        """
        if not paths or self.mode != "flash":
            return
        try:
            drive = self._resolve_circuitpy_drive()
            drive = self._verify_drive_for_board(drive)
        except CircuitpythonTransportError:
            return
        for device_path in paths:
            relative = device_path.lstrip("/")
            target = drive / relative
            try:
                target.unlink()
            except (OSError, FileNotFoundError):  # pragma: no cover — best-effort
                pass

    def wipe_filesystem(self) -> None:
        """Reformat the CIRCUITPY drive via ``storage.erase_filesystem()``.

        Flash mode only — RAM mode is a no-op (nothing in flash to
        wipe).  Drives the on-board nuclear option through raw REPL:
        the call reformats the FAT volume and reboots the board.
        The host-side serial session goes away mid-call as USB-CDC
        drops; the failure that surfaces is expected and swallowed.
        After waiting for the reformat + reboot to settle the port is
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
        except Exception:  # noqa: BLE001 — reboot kills the REPL mid-call
            pass
        try:
            self._port.close()
        except Exception:  # pragma: no cover — port may already be torn down
            pass
        self._port = None
        # Settle, then poll-reconnect.  USB-CDC takes a beat to come
        # back after ``storage.erase_filesystem()`` reformats the
        # volume + reboots; on boards with a populated FAT it can be
        # 6-10 seconds before the host sees the device again.  A
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

        ``storage.erase_filesystem()`` reboots the board; USB-CDC
        and the FAT volume mount on independent macOS timelines —
        CDC first, FAT typically a few seconds later.  The serial
        reconnect inside :meth:`wipe_filesystem` only waits for
        CDC, so a follow-up :meth:`deploy_files` immediately after
        wipe returns can race two distinct settle phases on the
        host side:

        1. Mount-not-yet-present — the configured drive path
           doesn't exist yet (FAT volume hasn't remounted at all).
        2. Mount-present-but-not-writable — the path is a directory
           but probe writes hit ``EACCES`` (macOS hasn't finished
           setting up access for the user).

        Both surface as deploy failures.  Reuses
        :meth:`_resolve_circuitpy_drive` in a retry loop because it
        already exercises both checks (``is_dir`` + tiny probe
        write/unlink); polling it covers either phase without
        duplicating the probe logic.  The poll waits for *any*
        CIRCUITPY mount to come back — :meth:`_verify_drive_for_board`
        on subsequent operations swaps to the connected board's mount
        on multi-board hosts.
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
        # Phrasing matches `_CIRCUITPY_DRIVE_PATTERNS["circuitpy
        # drive not mounted"]` in recovery.py so the recovery
        # classifier routes this to CIRCUITPY_DRIVE_MISSING — which
        # `_RecoveringDeployer._resolve_kind` then promotes to
        # MACOS_FSKIT_WEDGED when `detect_fskit_wedge()` reports True.
        # That promotion is the only host-visible signal that a
        # FAT-remount stall is the macOS FSKit wedge rather than a
        # generic timeout.
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

        ``execute_scripts`` delegates to :meth:`execute`, whose
        guard covers a test-harness invariant ("``stage()`` must be
        called before ``execute()``").  The RAM-mode deploy path
        flips :attr:`_staged` itself so the guard passes without
        mutating :attr:`_staged_sources` — deploy doesn't collect
        modules the same way ``stage()`` does, and pretending
        otherwise would leak the test path's shape into the deploy
        API surface.
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

        CP caches the FAT directory layout in RAM; an rsync that adds
        / removes / replaces files on the USB-MSC side updates the
        FAT on the device's flash, but the in-RAM cache may not pick
        up the new entries until something forces a directory read.
        Without this refresh, back-to-back ``_stage_to_flash`` calls
        on the same board can hit ``ImportError: no module named X.Y``
        because the freshly-rsynced module is on disk but invisible
        to CP's importer.

        Implementation: a recursive ``os.listdir`` walk from the FS
        root.  Listing a directory forces CP to re-read its FAT
        entries; walking covers nested package layouts (the typical
        ``/lib/<package>/<submodule>.py`` shape that the importer
        will hit next).

        Called from :meth:`_stage_to_flash` after the host-side
        ``flush_volume`` settle delay.  ``deploy_files`` (production
        path) handles the equivalent invalidation differently — it
        does an explicit soft-reboot via Ctrl-D after the rsync, which
        tears down + rebuilds the entire CP runtime including its
        FAT cache.  ``_stage_to_flash`` cannot soft-reboot because
        the harness expects the raw-REPL session to stay alive across
        the call.
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
        write in its FatFs view.  Slower USB-CDC controllers (Pi Pico W
        is the observed case) finish the host-visible write before CP
        has processed all block-write callbacks, so the next
        soft-reboot can re-execute the previous file — the capture is
        one cycle behind.

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
            f"{last_observed!r}) — USB-MSC write may not have committed."
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
        never appears and the read times out — callers receive the
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
            raw accumulated bytes are returned so callers / tests
            can still diagnose the failure.
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
            # Skip past the header + its trailing newline.
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
        raw REPL; a no-op control byte otherwise) so the next serial
        consumer never finds the board parked in raw REPL, then
        closes the port.  No Ctrl-C — that would interrupt any
        ``code.py`` left running by ``deploy_files``.  No
        ``supervisor.runtime.autoreload = True`` — flipping autoreload
        back on outside an active raw-REPL session can layer an
        autoreload-driven soft-reboot on top of one already in flight,
        which has historically wedged the ESP32-S2 USB-CDC firmware.

        When :meth:`reset_into_bootloader` has already been called, it
        closes the port itself and nulls :attr:`_port` — this method
        then finds nothing to close and only clears
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

    def _read_until(self, marker: bytes, idle_timeout: float | None = None) -> bytes:
        """Read from serial until *marker* is found or the link goes silent.

        Uses an **idle timeout** rather than a wall-clock deadline: bytes
        arriving reset the clock, only *idle_timeout* seconds of
        consecutive silence end the wait.  Defaults to ``self.timeout``
        when ``None``.

        Per-call override exists because two workload classes share this
        primitive: short interactive ops (autoreload toggle,
        ``gc.mem_free`` probe) finish in <1 s; test bootstraps can
        include silent CPU loops longer than that (the Lolin S2
        fragmentation-test bisection runs ~7,500 silent ``bytearray()``
        allocs at the 256-byte tier).  The bootstrap path passes a
        longer ``idle_timeout`` so the parser doesn't fire mid-script
        and raise "Malformed raw REPL response".

        Args:
            marker: Byte sequence to look for.
            idle_timeout: Seconds of consecutive silence that end the
                wait.  ``None`` means use ``self.timeout``.

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
                accumulated += chunk
                last_progress = self._time.monotonic()
                if marker in accumulated:
                    return accumulated
            else:
                self._time.sleep(0.01)
        return accumulated

    def _send_repl_command(self, command: str) -> str:
        """Send a command through raw REPL and return stdout.

        Used internally for control commands (autoreload, supervisor).
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
        # The response should start with "OK".
        response_text = raw_response.decode("utf-8", errors="replace")

        if not response_text.startswith("OK"):
            raise CircuitpythonTransportError(
                f"Raw REPL did not acknowledge code.  Response: {response_text!r}"
            )

        # Strip the leading "OK".
        after_ok = response_text[2:]

        # Split on \x04 to separate stdout and stderr.
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
