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

See Decision 0027 and Decision 0028 for the full transport protocol.
"""

from __future__ import annotations

import errno
import getpass
import os
import shutil
import tempfile
import time as _time_module
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from . import flash_drive
from .circuitpython_bootstrap import build_circuitpython_deploy_scripts
from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    parse_probe_output,
    validate_entrypoint_in_files,
)

_CTRL_A = b"\x01"
_CTRL_B = b"\x02"
_CTRL_C = b"\x03"
_CTRL_D = b"\x04"
_RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"
_SOFT_REBOOT_MARKER = b"soft reboot"

#: Default timeout in seconds for serial reads.
DEFAULT_TIMEOUT = 10.0

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
#: but there can still be in-flight block writes on the board side
#: (flash program/erase, FAT bookkeeping) that our polling can't
#: observe.  Sleeping a fraction of a second here gives those a
#: chance to quiesce before Ctrl-D kicks the VM into soft-reboot —
#: cheap insurance against hardware-level races the software layer
#: has no signal for.
_BOARD_FILE_VISIBLE_POST_SETTLE = 0.5

#: Volume name CircuitPython uses by default.
_CIRCUITPY_VOLUME_NAME = "CIRCUITPY"

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


def _format_probe_error(drive_path: Path, error: OSError) -> str:
    """Translate a probe-write OSError into a recovery-friendly message.

    The transport's ``.chu-probe`` write distinguishes three classes of
    failure on the drive:

    - ``ENOSPC`` — drive is full.  Includes the exact errno phrasing
      (``No space left on device``) so the recovery classifier's
      :data:`~chumicro_deploy.recovery._FLASH_DRIVE_STATE_PATTERNS`
      check picks it up.
    - ``EROFS`` — drive remounted read-only (rare on CIRCUITPY but
      possible after a USB hiccup or a board that booted into
      protected mode).
    - Anything else (typically ``EACCES`` from a stale Finder-eject
      mount) — kept as the original "not found or not writable"
      wrapper that documents both candidate causes.

    The first two are *drive-found* states, so the message no longer
    leads with "not found" — that was misleading when, e.g., the user
    was running a disk-full demo and saw the drive in Finder while
    chumicro-deploy claimed it wasn't there.
    """
    error_name = error.__class__.__name__
    error_text = str(error) or error_name
    if error.errno == errno.ENOSPC:
        return (
            f"CIRCUITPY drive at {drive_path} is full "
            f"({error_name}: {error_text})"
        )
    if error.errno == errno.EROFS:
        return (
            f"CIRCUITPY drive at {drive_path} is read-only "
            f"({error_name}: {error_text})"
        )
    return (
        f"CIRCUITPY drive not found or not writable: {drive_path} "
        f"({error_name}: {error_text})"
    )


def _resolve_username() -> str:
    """Return the host user name, with a fallback for environments
    that do not export ``$USER``.

    Reads ``$USER`` first (the value Linux desktops use for
    ``/media/<user>/`` mount paths); falls back to
    :func:`getpass.getuser` (which consults ``LOGNAME`` / ``LNAME`` /
    ``USERNAME`` and finally ``pwd.getpwuid(os.getuid())``) when
    ``$USER`` is unset, e.g. inside slim containers.  Returns the
    empty string when even the password database is unavailable so
    the caller can skip building malformed ``/media//CIRCUITPY``
    paths and try the macOS ``/Volumes/`` candidate instead.
    """
    user = os.environ.get("USER", "")
    if user:
        return user
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return ""


# RAM-mode inline scripts are chunked based on live free-heap measurements.
_MIN_INLINE_SCRIPT_BUDGET_BYTES = 8 * 1024
_MAX_INLINE_SCRIPT_BUDGET_BYTES = 48 * 1024


def _circuitpy_base_paths() -> list[Path]:
    """Return the OS-specific base directories that CIRCUITPY mounts under.

    macOS: ``/Volumes``.  Linux: ``/media/<user>``.  Linux (systemd):
    ``/run/media/<user>``.  Used by both the bare-name finder and
    the multi-mount glob so the discovery list lives in one place.
    """
    username = _resolve_username()
    bases = [Path("/Volumes")]
    if username:
        bases.append(Path("/media") / username)
        bases.append(Path("/run/media") / username)
    return bases


def find_circuitpy_drive() -> str | None:
    """Auto-detect the CIRCUITPY USB drive mount path.

    Checks common mount locations on macOS and Linux.  Returns the
    first path that exists as a directory, or ``None`` if no drive
    is found.  Bare-name only — does not match ``CIRCUITPY 1`` etc.;
    use :func:`_circuitpy_volume_candidates` for the multi-mount sweep.
    """
    for base in _circuitpy_base_paths():
        candidate = base / _CIRCUITPY_VOLUME_NAME
        if candidate.is_dir():
            return str(candidate)
    return None


def _circuitpy_volume_candidates() -> list[Path]:
    """Return every mounted CIRCUITPY* directory across the base paths.

    macOS assigns ``/Volumes/CIRCUITPY`` by mount order; additional
    CircuitPython boards get ``/Volumes/CIRCUITPY 1``, ``CIRCUITPY 2``,
    etc.  Globs all of them so the drive-verification path can scan
    every mounted device to find the one whose ``boot_out.txt``
    matches the connected board.  Bare-name match is included.
    """
    found: list[Path] = []
    for base in _circuitpy_base_paths():
        if not base.is_dir():
            continue
        for candidate in sorted(base.glob(f"{_CIRCUITPY_VOLUME_NAME}*")):
            if candidate.is_dir():
                found.append(candidate)
    return found


def _read_boot_out_text(drive_path: Path) -> str | None:
    """Return the full text of ``boot_out.txt`` on *drive_path*, or ``None``.

    Centralised so the identity reader has one error-swallowing policy.
    A missing or unreadable file yields ``None`` and the caller
    degrades gracefully.
    """
    boot_out = drive_path / "boot_out.txt"
    if not boot_out.is_file():
        return None
    try:
        return boot_out.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover — hard to mock read_text
        return None


def _read_boot_out_identity(
    drive_path: Path,
) -> tuple[str | None, str | None]:
    """Return ``(uid, machine)`` from ``boot_out.txt`` in one file read.

    CircuitPython writes ``boot_out.txt`` at boot with a header line::

        Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; Raspberry Pi Pico W with rp2040

    plus a ``UID:...`` line.  Both fields are needed by
    :meth:`CircuitpythonTransport._verify_drive_for_board` on every
    deploy and by the per-candidate identity sweep in
    :func:`find_circuitpy_drive_for_uid` /
    :func:`find_circuitpy_drive_for_machine`; reading once and
    extracting both avoids redundant I/O on a USB FAT mount.

    Either field is ``None`` when the file is missing, unreadable,
    or doesn't carry that field.
    """
    text = _read_boot_out_text(drive_path)
    if text is None:
        return None, None
    uid: str | None = None
    machine: str | None = None
    lines = text.splitlines()
    if lines:
        first_line = lines[0]
        semicolon_index = first_line.find(";")
        if semicolon_index != -1:
            machine = first_line[semicolon_index + 1:].strip()
    for line in lines:
        if line.startswith("UID:"):
            uid = line[len("UID:"):].strip().upper()
            break
    return uid, machine


def find_circuitpy_drive_for_uid(target_uid: str) -> str | None:
    """Return the mounted CIRCUITPY drive whose UID matches *target_uid*.

    Scans every mounted ``CIRCUITPY*`` volume, reads the ``UID:...``
    line from ``boot_out.txt``, and returns the first path whose UID
    equals *target_uid* (case-insensitive).  Returns ``None`` when no
    mount matches.  This is the preferred discovery path —
    :meth:`CircuitpythonTransport._verify_drive_for_board` only falls
    back to :func:`find_circuitpy_drive_for_machine` when the UID
    probe is unavailable on either side of the comparison.
    """
    if not target_uid:
        return None
    target = target_uid.upper()
    for candidate in _circuitpy_volume_candidates():
        uid, _machine = _read_boot_out_identity(candidate)
        if uid and uid == target:
            return str(candidate)
    return None


def _walk_package_sources(
    source_directory: Path,
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
            _walk_package_files(package_directory, package_directory.name),
        )
    return collected


def _walk_package_files(
    directory: Path,
    dotted_prefix: str,
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
                    ),
                )
        elif child.suffix == ".py":
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


def find_circuitpy_drive_for_machine(target_machine: str) -> str | None:
    """Return the mounted CIRCUITPY drive whose board matches *target_machine*.

    Fallback path when UID-based discovery isn't possible (older
    firmware that doesn't expose the UID probe, or a ``boot_out.txt``
    missing its ``UID:...`` line).  Scans every mounted ``CIRCUITPY*``
    volume, reads ``boot_out.txt``, and returns the first path whose
    board identity equals *target_machine*.  Returns ``None`` when no
    mount matches.  Cannot disambiguate two boards of the same model
    — prefer :func:`find_circuitpy_drive_for_uid` when the UID is
    known.
    """
    if not target_machine:
        return None
    for candidate in _circuitpy_volume_candidates():
        _uid, machine = _read_boot_out_identity(candidate)
        if machine and machine == target_machine:
            return str(candidate)
    return None


def _list_scope_on_drive(drive: Path) -> list[str]:
    """Walk a CIRCUITPY drive and return the deploy's in-scope paths.

    Flash-mode helper for :meth:`CircuitpythonTransport.list_files_in_scope`.
    Returns the four canonical state files (``/code.py``,
    ``/main.py``, ``/active.py``, ``/runtime_config.msgpack``) when
    they exist, plus every file under ``/lib/`` recursively.
    Out-of-scope files (user-uploaded images, hand-edited
    ``settings.toml``, the dotfile sentinels CIRCUITPY drops itself)
    are omitted so the diff routine never deletes them.
    """
    found: list[str] = []
    for filename in ("code.py", "main.py", "active.py", "runtime_config.msgpack"):
        if (drive / filename).is_file():
            found.append(f"/{filename}")
    lib_root = drive / "lib"
    if lib_root.is_dir():
        for path in sorted(lib_root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(drive).as_posix()
                found.append(f"/{relative}")
    return found


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
        circuitpy_drive_path: Host path to the CIRCUITPY USB drive.
            Used in ``mode="flash"``.  When omitted, auto-detected
            via ``find_circuitpy_drive()``.
        serial_port_factory: Callable that creates a serial port object.
            Accepts ``(port, baudrate, timeout)`` keyword arguments.
            Defaults to ``serial.Serial``.  Inject a fake for testing.
        time: Object providing ``monotonic()`` and ``sleep()`` methods.
            Defaults to Python's ``time`` module.
            Inject ``FakeTime`` for deterministic tests with no
            wall-clock waits.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        timeout: float = DEFAULT_TIMEOUT,
        mode: str = "ram",
        circuitpy_drive_path: str | None = None,
        serial_port_factory: Callable[..., object] | None = None,
        time: TimeSource | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self.mode = mode
        self.circuitpy_drive_path = circuitpy_drive_path
        self._serial_port_factory: Callable[..., object] = (
            serial_port_factory or self._default_serial_factory
        )
        self._time: TimeSource = time or cast(TimeSource, _time_module)
        self._port: SerialPort | None = None
        self._staged_sources: list[tuple[str, str]] | None = None
        #: True once ``stage()`` or the RAM-mode ``deploy_files`` path
        #: has prepared the transport for ``execute()`` calls.  Kept
        #: separate from ``_staged_sources`` so the deploy path does
        #: not have to pretend it staged modules it did not collect.
        self._staged: bool = False

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

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
    ) -> None:
        """Read source files into memory for inline execution.

        **Test-harness API.**  Sister of :meth:`deploy_files` for the
        ``test-libraries-functional`` orchestrator (`source_dirs` +
        `test_files` + `harness_source` are test-runner concepts).
        Production deploys use :meth:`deploy_files` with a flat
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
            extra_modules: Optional sibling Python files (e.g.
                ``_test_creds.py``) to register as importable on the
                device alongside library sources.  In RAM mode they
                join ``staged_sources``; in flash mode they land at the
                drive root next to the test files.
        """
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
            )
        self._staged = True

    def _verify_drive_for_board(self, drive_path: Path) -> Path:
        """Confirm *drive_path* is the CIRCUITPY mount for the connected board.

        macOS assigns ``/Volumes/CIRCUITPY`` in mount order, so a
        ``circuitpy_drive_path`` pinned in ``devices.yml`` can silently
        refer to the other board when two boards are attached.  This
        method probes the connected board and compares its identity
        against ``boot_out.txt`` on *drive_path*:

        1. **UID** (``microcontroller.cpu.uid`` ↔ ``UID:...`` line
           in ``boot_out.txt``) is preferred — it disambiguates two
           boards of the same model.
        2. **machine string** (``sys.implementation._machine`` ↔
           ``...; <machine>`` suffix on line 1) is the fallback for
           older firmware whose probe or ``boot_out.txt`` doesn't
           expose a UID.

        On a mismatch, every mounted ``CIRCUITPY*`` volume is scanned
        for one whose identity matches; the match wins, with a
        :func:`print` WARNING nudging the user to drop or fix the
        devices.yml override.  When no match is found a
        :class:`CircuitpythonTransportError` is raised.

        Fails open — when either side of either comparison is
        unavailable (``boot_out.txt`` missing/malformed, probe
        returns ``None``) the original path is returned unchanged.
        ``boot_out.txt`` is checked first so the serial-probe
        roundtrip is skipped entirely in environments that don't have
        it (test drives mocked with a bare ``tmp_path``, for instance).
        """
        boot_uid, boot_machine = _read_boot_out_identity(drive_path)
        if boot_uid is None and boot_machine is None:
            return drive_path
        probe = self.probe_implementation()
        if probe is None:
            return drive_path
        if probe.uid and boot_uid is not None:
            return self._resolve_identity_match(
                drive_path,
                identity_label="UID",
                drive_identity=boot_uid,
                probe_identity=probe.uid,
                mount_finder=find_circuitpy_drive_for_uid,
            )
        if probe.machine and boot_machine is not None:
            return self._resolve_identity_match(
                drive_path,
                identity_label="machine",
                drive_identity=boot_machine,
                probe_identity=probe.machine,
                mount_finder=find_circuitpy_drive_for_machine,
            )
        return drive_path

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
        WARNING / error messages.
        """
        if drive_identity == probe_identity:
            return drive_path
        corrected = mount_finder(probe_identity)
        if corrected is None:
            raise CircuitpythonTransportError(
                f"Configured CIRCUITPY drive {drive_path} "
                f"{identity_label}={drive_identity!r} does not match the "
                f"connected board ({identity_label}={probe_identity!r}).  "
                f"No other mounted CIRCUITPY* volume matches.  Remove or "
                f"fix circuitpy_drive_path in devices.yml (auto-detection "
                f"by UID works without it)."
            )
        print(
            f"WARNING: configured CIRCUITPY drive {drive_path} "
            f"{identity_label}={drive_identity!r} does not match the "
            f"connected board ({identity_label}={probe_identity!r}) — "
            f"auto-correcting to {corrected}.  Remove circuitpy_drive_path "
            f"from devices.yml to rely on UID-based auto-detection."
        )
        return Path(corrected)

    def _resolve_circuitpy_drive(self) -> Path:
        """Return the CIRCUITPY drive path, raising if it isn't usable.

        Uses the configured ``circuitpy_drive_path`` when set, otherwise
        falls back to :func:`find_circuitpy_drive`.  Raises when no drive
        can be found, the resolved path is not a directory, or the mount
        is stale/unwritable (e.g. the board was ejected from Finder and
        ``/Volumes/CIRCUITPY`` remains as an inaccessible placeholder —
        ``is_dir()`` returns True but file I/O fails with EACCES).
        The probe writes a tiny marker, so we catch the error up-front
        rather than halfway through the rsync / write-bytes pass.

        The probe-error message distinguishes drive-state failures
        (full / read-only / I/O error) from "found-but-stale-mount"
        EACCES so the recovery classifier and the user both see
        accurate text.  A disk-full drive is *found* — it just can't
        accept the write.
        """
        drive_path_str = self.circuitpy_drive_path or find_circuitpy_drive()
        if not drive_path_str:
            raise CircuitpythonTransportError(
                "CIRCUITPY drive not found.  Either set circuitpy_drive_path "
                "or connect the board's USB drive."
            )
        drive_path = Path(drive_path_str)
        if not drive_path.is_dir():
            raise CircuitpythonTransportError(
                f"CIRCUITPY drive not found: {drive_path}"
            )
        probe = drive_path / ".chu-probe"
        try:
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as error:
            raise CircuitpythonTransportError(
                _format_probe_error(drive_path, error),
            ) from error
        return drive_path

    @staticmethod
    def _build_local_staging_tree(
        staging_path: Path,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
    ) -> None:
        """Mirror the desired drive layout inside a local staging directory.

        Library and harness packages go under ``lib/``; test files and
        sibling extra modules go at the root.  Building locally is
        reliable (no FAT32 quirks) — only the rsync that follows has
        to deal with the device drive.  macOS extended attributes are
        stripped at the end so ``._`` resource forks don't end up on
        the FAT32 volume.
        """
        lib_staging = staging_path / "lib"
        lib_staging.mkdir()
        for source_directory in source_dirs:
            flash_drive.merge_packages(source_directory, lib_staging)
        flash_drive.merge_packages(harness_source, lib_staging)

        for test_file in test_files:
            shutil.copy2(test_file, staging_path / test_file.name)

        if extra_modules:
            for module_path in extra_modules:
                shutil.copy2(module_path, staging_path / module_path.name)

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

    def _stage_to_flash(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
    ) -> None:
        """Copy staged files to the CIRCUITPY USB drive via rsync.

        Builds a local staging directory that mirrors the desired drive
        layout — library and harness packages under ``lib/``, test
        files at the root — then rsyncs the whole thing to the drive
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
        drive_path = self._resolve_circuitpy_drive()
        drive_path = self._verify_drive_for_board(drive_path)

        # macOS hygiene: disable Spotlight + plant persistent skip
        # sentinels + remove noise directories, before the rsync runs.
        flash_drive.disable_spotlight_indexing(drive_path)
        flash_drive.neuter_macos_metadata(drive_path)

        # Disable autoreload to prevent the board restarting mid-copy.
        # Restoration is intentionally NOT local to this method: the
        # symmetric ``autoreload = True`` lives in :meth:`disconnect`,
        # which always runs (Deployer wraps deploy_files in a
        # try/finally → disconnect()).  Locality was rejected because
        # disconnect() must restore anyway — it follows a soft-reboot
        # that needs autoreload back on, and after a soft-reboot raw
        # REPL is gone so the inline send would race the re-enter.
        # Two restores per deploy was the cost of doing it locally
        # too.  If you call this transport directly without going
        # through Deployer, call ``disconnect()`` to restore.
        self._send_repl_command(
            "import supervisor; "
            "supervisor.runtime.autoreload = False"
        )

        with tempfile.TemporaryDirectory() as staging_directory:
            staging_path = Path(staging_directory)
            self._build_local_staging_tree(
                staging_path, source_dirs, test_files, harness_source,
                extra_modules=extra_modules,
            )
            try:
                flash_drive.rsync(
                    staging_path,
                    drive_path,
                    # Functional tests want a clean slate between test
                    # files (stale test code from a prior run would
                    # confuse the harness); preserve firmware user-
                    # config files the device needs across runs.
                    delete=True,
                    additional_excludes=flash_drive.FUNCTIONAL_TEST_EXTRA_EXCLUDES,
                )
            except flash_drive.FlashDriveError as error:
                raise CircuitpythonTransportError(str(error)) from error

        # Remove ._ resource fork files that macOS may have created
        # on the FAT32 volume despite rsync's --exclude=._* flag.
        flash_drive.clean_dot_files(drive_path)

        # Flush the volume so the device reads current content.
        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

        self._warn_if_flush_produced_empty_file(drive_path, test_files)

    def _collect_package_sources(self, source_directory: Path) -> None:
        """Walk a source directory and extend ``_staged_sources``.

        Thin adaptor around :func:`_walk_package_sources` that keeps
        the transport's mutable state contained to this one method.
        """
        assert self._staged_sources is not None
        self._staged_sources.extend(_walk_package_sources(source_directory))

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
        raw_response = self._read_until(b"\x04>")

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

        CircuitPython's ``microcontroller.on_next_reset`` +
        ``microcontroller.reset()`` sequence is the canonical way to
        drop out of user code and enter the board's UF2 bootloader.
        The raw-REPL session is killed as the board resets —
        expected — so read-side exceptions are swallowed.  The
        caller's drive-poll is the authoritative success signal.

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

        drive_path = self._resolve_circuitpy_drive()

        self._enter_raw_repl()
        drive_path = self._verify_drive_for_board(drive_path)
        # macOS hygiene before the writes: disable Spotlight, plant
        # persistent skip sentinels, remove noise directories.  Without
        # this, macOS creates ._foo AppleDouble resource forks for every
        # file written through a FAT mount — the board's os.listdir
        # sees ~2x the file count, doubling apparent on-disk footprint.
        flash_drive.disable_spotlight_indexing(drive_path)
        flash_drive.neuter_macos_metadata(drive_path)
        # Disable autoreload to prevent the board restarting mid-copy.
        # Restoration is intentionally NOT local to this method: the
        # symmetric ``autoreload = True`` lives in :meth:`disconnect`,
        # which always runs (Deployer wraps deploy_files in a
        # try/finally → disconnect()).  Locality was rejected because
        # disconnect() must restore anyway — it follows the
        # Ctrl-B/Ctrl-D soft-reboot below that needs autoreload back
        # on, and the soft-reboot tears down raw REPL so any inline
        # send here would race the re-enter.  Two restores per deploy
        # was the cost of doing it locally too.  If you call this
        # transport directly without going through Deployer, call
        # ``disconnect()`` to restore.
        self._send_repl_command(
            "import supervisor; supervisor.runtime.autoreload = False"
        )

        # Build a local staging tree mirroring the desired drive
        # layout, then rsync it onto the drive.  Single primitive both
        # this path and ``_stage_to_flash`` (functional tests) share
        # so we have one set of FAT-write reliability guarantees
        # (``--checksum`` + ``--inplace`` to dodge the failure modes
        # of direct per-file ``Path.write_bytes`` on USB-MSC FAT32).
        # ``delete=False`` preserves user-data files on the drive
        # that aren't part of the deploy's file map (``settings.toml``,
        # custom modules); ``chumicro-workspace deploy --wipe`` is the
        # destructive escape hatch.
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
                flash_drive.strip_extended_attributes(staging_path)
                flash_drive.rsync(
                    staging_path,
                    drive_path,
                    delete=False,
                )
        except flash_drive.FlashDriveError as rsync_error:
            raise CircuitpythonTransportError(
                str(rsync_error),
            ) from rsync_error
        except OSError as error:
            # The host-side staging-tree build can still hit OSError
            # (out of /tmp space, etc.); the probe-pass guarantee
            # covered the drive itself.  Re-raise with the same
            # wrapper the probe path uses so the classifier routes
            # disk-full / RO to FLASH_COPY_FAILED instead of
            # CIRCUITPY_DRIVE_MISSING.
            raise CircuitpythonTransportError(
                _format_probe_error(drive_path, error),
            ) from error

        # Strip macOS AppleDouble (._foo) companions before flushing.
        flash_drive.clean_dot_files(drive_path)
        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

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
        output = self._read_code_py_output()

        # Re-enter raw REPL so disconnect()'s cleanup (autoreload on,
        # soft-reboot, exit) has a live session to work from.
        self._enter_raw_repl()

        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self) -> list[str]:
        """List on-device files within the deploy's managed scope.

        Flash mode walks the CIRCUITPY USB drive directly via stdlib
        ``pathlib`` — faster + simpler than a raw-REPL round-trip,
        and the drive's contents *are* the device's filesystem.

        RAM mode returns an empty list — RAM-mode deploys never
        touch flash, so there's nothing persistent to diff between
        deploys.
        """
        if self.mode != "flash":
            return []
        try:
            drive = self._resolve_circuitpy_drive()
        except CircuitpythonTransportError:
            return []
        return _list_scope_on_drive(drive)

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the CIRCUITPY drive.

        Flash mode only — RAM mode is a no-op since nothing was
        ever written to flash.  Each path is normalised to a
        leading-slash form, joined under the CIRCUITPY mount point,
        and unlinked best-effort.  Missing paths and per-path errors
        are tolerated silently so a transient I/O hiccup never blocks
        the deploy that follows.

        Uses :meth:`pathlib.Path.unlink` rather than rsync ``--delete``
        on purpose: rsync's delete semantics are "remove anything in
        DEST not in SRC" — wrong shape for "delete these specific
        files."  Unlink also dodges FAT32's data-write reliability
        concerns (Decision 0033) by only touching directory entries,
        no payload bytes.  The diff layer recomputes the stale set
        on every deploy, so a swallowed error here just retries
        next time.
        """
        if not paths or self.mode != "flash":
            return
        try:
            drive = self._resolve_circuitpy_drive()
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
                return
            except CircuitpythonTransportError as connect_error:
                last_error = connect_error
                self._time.sleep(_WIPE_RECONNECT_POLL_SECONDS)
        raise CircuitpythonTransportError(
            f"Failed to reconnect to {self.address} within "
            f"{_WIPE_RECONNECT_TIMEOUT_SECONDS:.0f}s of "
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

    def _read_code_py_output(self) -> str:
        """Read serial output from a fresh boot until code.py completes.

        CircuitPython prints ``soft reboot`` when the interpreter
        restarts (in response to Ctrl-D from the friendly REPL) and
        ``Code done running.`` when code.py returns (or raises).  The
        read synchronises on ``soft reboot`` first so any pre-reboot
        bytes still in the host's serial buffer (slow boards can hold
        a complete previous-cycle ``code.py output: ... Code done
        running.`` pair, especially when autoreload had been enabled
        during the last session) are discarded rather than mistaken
        for this cycle's output.

        For infinite-loop entrypoints the ``Code done running.`` marker
        never appears and the read times out at :attr:`timeout`
        seconds — callers receive the accumulated output up to that
        point.

        Returns:
            The portion of captured serial output between the
            ``code.py output:`` header and the ``Code done running.``
            marker (if present), or everything after ``soft reboot``
            otherwise.  When ``soft reboot`` is never observed the
            raw accumulated bytes are returned so callers / tests
            can still diagnose the failure.
        """
        assert self._port is not None
        done_marker = b"Code done running."
        accumulated = b""
        deadline = self._time.monotonic() + self.timeout
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

        Restores the board to normal operation regardless of mode:

        1. Re-enters raw REPL (in case a reset exited it).
        2. In flash mode, re-enables autoreload via supervisor —
           **this is the canonical restoration site** for the
           ``autoreload = False`` that :meth:`_stage_to_flash` and
           :meth:`deploy_files` (flash path) issue at the top of
           their write windows.  Those methods deliberately do NOT
           restore locally; see the disable-site comment for the
           reasoning.
        3. Exits raw REPL with Ctrl-B (back to normal REPL).
        4. Soft-reboots with Ctrl-D so code.py runs normally.
        5. Waits briefly for the reboot to complete.
        6. Closes the serial port.

        When :meth:`reset_into_bootloader` has already been called,
        it closes the port itself and nulls :attr:`_port` — this
        method then finds nothing to restore or close and only
        clears :attr:`_staged_sources`.
        """
        if self._port is not None:
            try:
                self._enter_raw_repl()
                if self.mode == "flash":
                    self._send_repl_command(
                        "import supervisor; "
                        "supervisor.runtime.autoreload = True"
                    )
                # Exit raw REPL back to normal REPL.
                self._port.write(_CTRL_B)
                self._time.sleep(_ENTER_DELAY)
                # Soft-reboot so code.py starts normally.
                self._port.write(_CTRL_D)
                self._time.sleep(0.5)
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

    def _read_until(self, marker: bytes) -> bytes:
        """Read from serial until *marker* is found or the link goes idle.

        Uses an **idle timeout** rather than a fixed wall-clock deadline:
        as long as new bytes keep arriving, ``_read_until`` keeps reading.
        Only ``self.timeout`` seconds of *consecutive silence* end the
        wait.

        Why: long-running scripts (functional-test chunks doing wifi
        connect + MQTT QoS 1 round-trip + LAN echo, e.g. 15-30 s of
        device-side work) emit output across the whole window and only
        send the trailing ``\\x04>`` markers when the script finishes.
        A wall-clock-bounded read aborts mid-script with a partial
        buffer like ``'OKWIFI_OK ip=…\\r\\n'`` (verified live on
        Pi Pico W CP / Lolin S2 CP, 2026-04-28) and
        :meth:`_parse_raw_repl_response` raises a confusing
        "Malformed raw REPL response (missing \\x04 markers)" error.
        Idle-timeout semantics let the read keep up with the script's
        natural pacing while still bounding the no-data case.

        Args:
            marker: Byte sequence to look for.

        Returns:
            All bytes read, including the marker if found.  When the
            wait ends due to idle timeout, returns whatever was
            accumulated.
        """
        assert self._port is not None
        accumulated = b""
        last_progress = self._time.monotonic()
        while self._time.monotonic() - last_progress < self.timeout:
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
