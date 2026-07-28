"""MicroPython device transport using mpremote.

Two execution paths:

- **Persistent serial transport** (mount mode and per-execute path):
  uses ``mpremote.transport_serial.SerialTransport`` directly.  Opens
  the serial port once per session, enters raw REPL once, mounts the
  staging directory once, and runs each bootstrap via ``exec_raw``.
  Avoids the cold-start cost of spawning ``mpremote`` per
  ``execute()`` call.
- **Subprocess fallback** (copy mode staging, reset/recover): uses the
  ``mpremote`` CLI for operations that are one-shot and easier to express
  via the CLI.  The serial port is closed before these calls and
  reopened on the next ``execute()``.

"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time as _time_module
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from ._device_scripts import (
    CLEAR_ENTRYPOINTS_SCRIPT,
    LIST_ALL_SCRIPT,
    LIST_SCOPE_SCRIPT,
    WIPE_FILESYSTEM_SCRIPT,
    clean_slate_script,
    delete_files_script,
    parse_scope_listing,
    remove_entries_script,
)
from ._line_dispatcher import StreamingLineDispatcher
from .flash_drive import DEVICE_KEEP_SET
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
from .source_minify import minify_python_tree

if TYPE_CHECKING:  # pragma: no cover - type-only
    from mpremote.transport_serial import SerialTransport


#: Idle timeout (seconds) for ``exec_raw`` on the bootstrap path
#: (``execute()`` / ``deploy_files()``).  This is mpremote's inter-byte
#: ``read_until`` timeout, **not** a wall-clock budget: every received
#: byte resets the clock, so it bounds only a run of *consecutive
#: silence*.  Sized large because on-device tests can run long
#: allocation loops that emit no output for minutes.  Short
#: interactive ops (probe, scope listing, delete, wipe, bootloader)
#: keep their own short timeouts.
_EXECUTE_IDLE_TIMEOUT: float = 300.0

#: Wall-clock cap on a single ``mpremote`` subprocess call (connect, fs
#: cp, exec, wipe).  Generous so a large file copy over serial isn't
#: false-timed-out, but finite so a board whose USB-CDC wedges mid-command
#: can't hang the deploy forever.  The timeout becomes a classified
#: MicropythonTransportError instead.
_MPREMOTE_SUBPROCESS_TIMEOUT: float = 120.0

#: Idle timeout (seconds) for the short interactive raw-REPL ops
#: (scope listing, delete, clear-entrypoints).  These scripts print
#: little and return fast, so a tight bound catches a wedged board
#: sooner than :data:`_EXECUTE_IDLE_TIMEOUT` would.
_INTERACTIVE_OP_TIMEOUT: float = 30.0


class MicropythonTransportError(DeviceTransportError):
    """Raised when an mpremote command fails."""


class MicropythonMidDeployDisconnected(
    MicropythonTransportError, MidDeployDisconnected,
):
    """Raised when the device drops mid-deploy.

    The MicroPython face of :class:`.protocol.MidDeployDisconnected`
    (which owns the message shape and the :attr:`cause` attribute).
    """


#: Directory / file basenames the test-harness staging path skips when
#: copying library `src/` trees into the device-bound staging dir.
#: Keeps host-only build artifacts (bytecode caches, VCS dirs, IDE
#: caches) off device flash.  ``*.pyc`` and ``*.egg-info`` are matched
#: by suffix elsewhere.
_STAGE_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache"},
)


#: Wall-clock pause between issuing ``machine.soft_reset()`` (inside
#: :data:`._device_scripts.WIPE_FILESYSTEM_SCRIPT`) and re-opening the persistent
#: serial transport.  rp2 and esp32 keep their host-side USB-CDC alive
#: across a soft reset, so this is settle time for the runtime to
#: remount ``/`` on the freshly-formatted volume.
_WIPE_REBOOT_SETTLE_SECONDS: float = 2.0


#: Bounded retry for the subprocess reset path when a wedged board
#: (e.g. one that hit ``ENOSPC`` mid-stage) has dropped and is
#: re-enumerating its USB-CDC.  ``mpremote connect <port> reset`` then
#: fails ``it may be in use by another program`` / ``device not
#: configured`` for the re-enumeration window; the settle rides that
#: window out before returning so the next per-library reset doesn't
#: race it.  Reuses the wipe-reboot settle value.
_RESET_RETRY_ATTEMPTS: int = 4
_RESET_RETRY_SETTLE_SECONDS: float = _WIPE_REBOOT_SETTLE_SECONDS


def _resolve_mpremote_binary() -> str:
    """Return the ``mpremote`` executable path to invoke via subprocess.

    ``mpremote`` is a ``requirements-dev.txt`` dependency, so it lands in
    ``.venv/bin/mpremote`` after workspace setup.  Shelling out with the
    bare name only works when ``.venv/bin`` is on ``PATH``
    (i.e. after ``source .venv/bin/activate``), which fails for direct
    ``.venv/bin/python`` invocations and for IDE play buttons that
    launch via the interpreter path without an activated shell.

    Prefer the binary next to the running interpreter; fall back to the
    bare name so a system-wide or externally-managed ``mpremote`` still
    works.  Windows resolution is handled via ``shutil.which`` since the
    binary there is ``mpremote.exe``.
    """
    import shutil

    interpreter_bin = Path(sys.executable).parent
    for candidate in (interpreter_bin / "mpremote", interpreter_bin / "mpremote.exe"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    resolved = shutil.which("mpremote")
    return resolved or "mpremote"


def _decode_exec_result(result: Any) -> str:
    """Normalize an ``mpremote.SerialTransport.exec_raw`` return value to text.

    mpremote returns ``(stdout_bytes, stderr_bytes)`` in newer versions and
    raw ``bytes`` (or already-decoded ``str``) in older ones.  Tracebacks
    land on stderr, so both streams are merged, and callers downstream
    parse the combined output with ``result_parser.parse_output``.

    Args:
        result: Return value from ``exec_raw`` (tuple, bytes, or str).

    Returns:
        UTF-8 decoded text with stderr appended to stdout.
    """
    if isinstance(result, tuple):
        # mpremote's exec_raw return shape has drifted across versions, so
        # accept a 1-tuple (stdout only) and ignore extras in a 3-tuple
        # instead of raising on a fixed two-value unpack.
        stdout_bytes = result[0] if len(result) >= 1 else b""
        stderr_bytes = result[1] if len(result) >= 2 else b""
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        return stdout + stderr
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="replace")
    return result


def _default_transport_factory(address: str, baudrate: int) -> SerialTransport:
    """Default :class:`SerialTransport` factory.

    Importing inside the call so a monkey-patched factory does not
    require ``mpremote`` to be installed.

    Args:
        address: Serial port path (e.g. ``/dev/cu.usbmodem1234``).
        baudrate: Serial baud rate.
    """
    # pragma: no cover - exercised on real hardware only
    from mpremote.transport_serial import SerialTransport

    return SerialTransport(address, baudrate=baudrate)


class MicropythonTransport:
    """Transport for MicroPython boards.

    Args:
        address: Serial port or network address of the device.
        baudrate: Serial baud rate (default 115200).  Only used for the
            persistent serial transport, because subprocess ``mpremote``
            invocations negotiate baud rate themselves.
        mode: ``"mount"`` (default) or ``"copy"``.
        runner: Callable that executes subprocess commands.  Accepts
            the same signature as ``subprocess.run``.  Defaults to
            ``subprocess.run``.
        transport_factory: Callable that builds a :class:`SerialTransport`
            given ``(address, baudrate)``.  Defaults to
            :func:`_default_transport_factory`.  Inject a fake to
            avoid opening a real serial port.
        time: Object providing ``monotonic()`` and ``sleep()``.  Defaults
            to Python's ``time`` module.  Inject :class:`FakeTime` (from
            :mod:`chumicro_deploy.testing`) to eliminate wall-clock waits.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        mode: str = "mount",
        timeout: float = 10.0,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        transport_factory: Callable[[str, int], Any] | None = None,
        time: TimeSource | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.mode = mode
        #: Wall-clock budget (10 s default) for the soft-reboot read
        #: in :meth:`deploy_files` ``follow="soft_reboot"``.  Sized for
        #: the partial-output window for ``while True`` app code.
        #: ``follow="exec"`` ignores this: that path uses
        #: :data:`_EXECUTE_IDLE_TIMEOUT` (an inter-byte idle timeout,
        #: not a wall-clock budget) for raw-REPL EOF reception.
        self.timeout = timeout
        self._runner = runner or subprocess.run
        self._transport_factory = transport_factory or _default_transport_factory
        self._time: TimeSource = time or cast("TimeSource", _time_module)
        self._staging_dir: tempfile.TemporaryDirectory | None = None
        self._staging_path: Path | None = None
        self._serial: Any = None
        self._mounted: bool = False
        #: Top-level device-root names written by the last copy-mode
        #: :meth:`stage`.  ``mpremote fs cp`` is additive and has no
        #: deletion flag, so a multi-library sweep must delete the
        #: prior library's tree before the next ``fs cp`` or the device
        #: LittleFS fills and staging hits ``ENOSPC``.  Persists for
        #: the transport's life (one transport per device across the
        #: whole sweep).
        self._staged_device_entries: list[str] = []
        #: The deployment target is MicroPython, so files marked for
        #: another runtime via ``__chumicro_runtimes__`` are filtered out
        #: of the staging tree.  Sub-runtime markers
        #: (``micropython_esp32`` / ``micropython_rp2``) fold into
        #: ``"micropython"``.
        self._target_runtime: str = "micropython"
        #: Set per :meth:`stage` call.  When ``True``, test-support
        #: fakes reach the board; product / app / functional deploys
        #: leave it ``False``.
        self._include_test_support: bool = False
        #: The first copy-mode :meth:`stage` mkfs-wipes the board so the
        #: sweep never inherits residue from a prior killed run (the
        #: additive-``fs cp`` accumulation described on
        #: :attr:`_staged_device_entries`).  In-process incremental
        #: cleanup handles every stage after this one.
        self._did_initial_wipe: bool = False

    def connect(self) -> None:
        """Verify the device is reachable by running a no-op command.

        Uses subprocess so the persistent serial transport is opened
        lazily on the first ``execute()`` (or eagerly during mount-mode
        ``stage()``).  Avoids holding the serial port during the gap
        between ``connect()`` and ``stage()``.
        """
        self._run_mpremote(["exec", "print('ok')"])

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
        """Prepare a staging directory with library sources, tests, and harness.

        In mount mode, the staging directory is mounted on the device
        via the persistent serial transport.  In copy mode, it is
        recursively copied to flash via ``mpremote fs cp -r``.

        Safe to call repeatedly on the same transport (RAM-mode
        orchestration re-stages per file).  On re-stage in mount mode
        the existing mount is dropped first.  Otherwise mpremote's
        ``mount_local`` hits ``OSError: [Errno 1] EPERM`` because the
        device-side mount hook refuses to replace a live mount.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage.
            harness_source: Path to the test harness ``src/`` directory.
            extra_modules: Optional sibling Python files to copy to
                the staging root next to the test files.
            extra_files: Non-Python files to land at named device paths
                (typically ``{"/runtime_config.msgpack": <bytes>}``) so
                test code can call ``chumicro_config.load_runtime_config()``.
                **Copy mode only.**  Copy mode rsyncs the staging tree to
                flash, so a file staged for ``/runtime_config.msgpack``
                lands at that absolute path.  **Mount mode raises**
                :class:`UnsupportedExtraFilesError`: mpremote
                ``mount_local`` lands the staging tree at ``/remote``, so
                the bytes would appear at ``/remote/runtime_config.msgpack``,
                invisible to a reader that opens the absolute
                ``/runtime_config.msgpack``.

        Raises:
            UnsupportedExtraFilesError: ``mode == "mount"`` and
                *extra_files* is non-empty.  Switch the device's
                ``deploy_mode`` to ``"copy"`` to fix.
        """
        if extra_files and self.mode == "mount":
            raise UnsupportedExtraFilesError(
                "MicropythonTransport(mode='mount') cannot stage extra_files "
                f"({sorted(extra_files.keys())!r}): mpremote mount_local "
                "lands the staging tree at /remote, so a file staged for an "
                "absolute device path like /runtime_config.msgpack would "
                "appear at /remote/runtime_config.msgpack and stay invisible "
                "to a reader opening the absolute path.  Set the device's "
                "deploy_mode to 'copy' before staging tests that need a "
                "runtime_config or other on-device file.",
            )

        self._include_test_support = include_test_support
        # Drop any mount/tempdir left from a prior stage() on this
        # transport so a re-stage starts from a clean tempdir.
        self._drop_active_mount()
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_device_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        # Library + harness packages go under lib/ in copy mode so they
        # import through the device's /lib with production sys.path order
        # (MP's default ['', '.frozen', '/lib']).  Staging them at the
        # device root would resolve them via the '' entry that precedes
        # '.frozen', masking a frozen-module shadow the real /lib deploy
        # would hit.  Mount mode keeps them at the staging root: mpremote
        # mount_local lands the tree at /remote and inserts /remote (not
        # /remote/lib) on sys.path.
        library_root = staging_path / "lib" if self.mode == "copy" else staging_path
        library_root.mkdir(parents=True, exist_ok=True)
        for source_dir in source_dirs:
            self._copy_tree(source_dir, library_root)

        self._copy_tree(harness_source, library_root)

        for test_file in test_files:
            destination = staging_path / test_file.name
            destination.write_bytes(test_file.read_bytes())

        # Copy extra sibling modules into the staging root so the test
        # source's `from _foo import ...` line resolves against a real
        # file on the device.
        if extra_modules:
            for module_path in extra_modules:
                destination = staging_path / module_path.name
                destination.write_bytes(module_path.read_bytes())

        # Land binary extra_files at their declared device paths inside
        # the staging tree.  Copy mode rsync's the whole tree to flash,
        # and mount mode mounts the tree as the device filesystem.  Either
        # way, the file appears at the requested device path.  Leading
        # slash stripped to make the device-path → staging-path
        # translation reversible.
        if extra_files:
            for device_path, content in extra_files.items():
                relative = device_path.lstrip("/")
                if not relative:
                    raise MicropythonTransportError(
                        f"extra_files key {device_path!r} has no path "
                        "component; expected a leading-slash path like "
                        '"/runtime_config.msgpack"',
                    )
                destination = staging_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)

        # Strip docstrings and comments from every staged .py before the
        # transfer so libraries, tests, and the harness land as code only.
        minify_python_tree(staging_path)
        if self.mode == "copy":
            # Subprocess `fs cp -r`, so release the serial port if held.
            self._close_serial()
            # `mpremote fs cp` only adds/overwrites, never deletes, so
            # a stale tree must be cleared or LittleFS fills and `fs cp`
            # hits ENOSPC.  The first stage may meet residue from a
            # prior killed run that no in-process tracking saw, so it
            # cleans the whole device, not just tracked roots, while
            # preserving `DEVICE_KEEP_SET`.  Later stages only delete
            # the prior stage's library/test roots (never keep-set
            # names).
            if not self._did_initial_wipe:
                self._clean_slate_device()
                self._did_initial_wipe = True
            elif self._staged_device_entries:
                self._remove_device_entries(self._staged_device_entries)
            self._run_mpremote([
                "fs", "cp", "-r",
                str(staging_path) + "/.",
                ":",
            ])
            self._staged_device_entries = sorted(
                entry.name for entry in staging_path.iterdir()
            )
        else:
            # Mount mode: open the persistent transport now and mount
            # the staging dir so every subsequent execute() reuses both.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True

    def execute(
        self,
        bootstrap_script: str,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Execute a bootstrap script on the device and return captured output.

        Uses the persistent serial transport's ``exec_raw`` so each call
        amortizes the one-time mpremote-cold-start cost.  In copy mode
        the serial transport is opened lazily (since ``stage()`` released
        it for the ``fs cp`` subprocess).

        Args:
            bootstrap_script: Python code to execute on the device.
            on_line: Optional callback invoked with each stdout line as
                it arrives over the serial link, before this method
                returns.  Lines are delivered without their trailing
                newline; ``\\r\\n`` is normalized to ``\\n``.  Wires
                straight into mpremote's ``data_consumer`` hook on
                ``exec_raw``, which fires per byte during the stdout
                read phase and stops at the ``\\x04`` end-of-stdout
                marker.  The dispatcher discards that terminator byte
                so callbacks only see board content.

        Returns:
            Captured stdout from the device.
        """
        if self._staging_path is None:
            raise MicropythonTransportError(
                "stage() must be called before execute()"
            )
        self._ensure_serial()
        line_dispatcher = (
            StreamingLineDispatcher(on_line, terminator=b"\x04")
            if on_line is not None
            else None
        )
        # mpremote's ``read_until(data_consumer=...)`` *replaces* its
        # internal ``data`` byte on every read instead of appending, so
        # ``exec_raw`` returns empty stdout when a consumer is wired.
        # Accumulate raw stdout bytes in a parallel buffer so the
        # captured-output contract survives the streaming path.
        captured_stdout_bytes: bytearray | None = (
            bytearray() if line_dispatcher is not None else None
        )

        def dispatch_and_capture(chunk: bytes) -> None:
            assert captured_stdout_bytes is not None
            assert line_dispatcher is not None
            captured_stdout_bytes.extend(chunk)
            line_dispatcher.feed(chunk)

        try:
            if line_dispatcher is not None:
                result = self._serial.exec_raw(
                    bootstrap_script,
                    timeout=_EXECUTE_IDLE_TIMEOUT,
                    data_consumer=dispatch_and_capture,
                )
            else:
                result = self._serial.exec_raw(
                    bootstrap_script, timeout=_EXECUTE_IDLE_TIMEOUT,
                )
        except Exception as error:
            raise MicropythonTransportError(
                f"Device exec failed: {error}"
            ) from error
        if line_dispatcher is not None:
            line_dispatcher.flush()
            # mpremote feeds the trailing ``\x04`` end-of-stdout byte
            # to the consumer before exiting its read loop; strip it
            # from the captured bytes so callers see clean stdout.
            assert captured_stdout_bytes is not None
            stdout_text = bytes(captured_stdout_bytes).rstrip(b"\x04").decode(
                "utf-8", errors="replace",
            )
            stderr_bytes = (
                result[1] if isinstance(result, tuple) and len(result) >= 2 else b""
            )
            stderr_text = (
                stderr_bytes.decode("utf-8", errors="replace")
                if stderr_bytes
                else ""
            )
            return stdout_text + stderr_text
        return _decode_exec_result(result)

    def run_script(self, script: str, *, timeout: float = 10.0) -> str:
        """Run *script* via the persistent serial REPL with no staging.

        Opens the raw REPL if needed and runs the script directly via
        ``exec_raw``.  Bypasses the ``stage()``-first precondition
        that :meth:`execute` enforces because *script* is expected to
        be self-contained (no imports of staged modules).

        Args:
            script: Self-contained Python source to run.
            timeout: Idle-timeout for the script's output, in seconds.

        Returns:
            Captured stdout from the device.
        """
        return self._exec_or_classify(
            script, timeout=timeout, failure_context="Device run_script failed",
        )

    def soft_reset(self) -> None:
        """Soft-reset the device to clear interpreter state.

        Sends Ctrl-D through the persistent raw REPL.  This clears
        ``sys.modules`` and the device heap without toggling USB, so
        it is safe to run between every file.

        The mount is **not** restored by this method.  Callers always
        call ``stage()`` next, and ``stage()`` owns the fresh mount.
        Restoring the mount here would double-wrap mpremote's
        ``SerialIntercept`` (``mount_local`` unconditionally wraps
        ``self.serial``) and garble subsequent I/O.

        Leaves the interpreter clean and the serial un-wrapped.  If no
        persistent transport is open, falls back to a subprocess
        ``mpremote reset`` with a bounded settle-and-retry: a prior hard failure
        (e.g. a stage ``ENOSPC``) can wedge the board so its USB-CDC
        re-enumerates, and the first ``mpremote connect ... reset``
        then fails ``it may be in use by another program``.  Retrying
        across that window keeps one library's failure from cascading
        through every subsequent per-library reset.
        """
        if self._serial is None:
            self._subprocess_reset_with_retry()
            return

        # Umount while the device-side mount state is still live.  After
        # Ctrl-D the ``os`` module and mount hook are gone and
        # ``umount_local`` would error when it tries to run
        # ``os.umount(...)``.
        self._drop_active_mount()
        try:
            self._serial.exit_raw_repl()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        self._serial.enter_raw_repl(soft_reset=True)

    def recover(self) -> None:
        """Attempt to recover after a failed test.

        Closes the persistent transport (if open) and reconnects from
        scratch.  More aggressive than :meth:`soft_reset` because the
        previous failure might have left the raw REPL in an unknown
        state where ``exit_raw_repl`` itself could hang.
        """
        self._close_serial()
        # Subprocess reset so we don't immediately try to grab the port
        # again.  mpremote handles the whole open/reset/close cycle.
        # The retry+settle rides out a USB-CDC re-enumeration on a
        # wedged board and settles before returning, so the next
        # per-library stage()/soft_reset() doesn't race the reboot.
        try:
            self._subprocess_reset_with_retry()
        except MicropythonTransportError:  # pragma: no cover - hardware-only
            pass

    def _subprocess_reset_with_retry(self) -> None:
        """Subprocess ``mpremote ... reset``, riding out re-enumeration.

        Runs ``mpremote reset`` in a retry loop with a settle pause
        between attempts and one final settle on success.  A board
        wedged by a prior failure can drop its USB-CDC and reject
        ``mpremote connect <port> reset`` with "in use" or "device not
        configured" until it re-enumerates, so the loop bridges that
        window.  The trailing settle keeps the next port grab from
        landing mid-re-enumeration.  Raises only when every attempt
        fails.
        """
        last_error: Exception | None = None
        for _attempt in range(_RESET_RETRY_ATTEMPTS):
            try:
                self._run_mpremote(["reset"])
            except MicropythonTransportError as error:
                last_error = error
                self._time.sleep(_RESET_RETRY_SETTLE_SECONDS)
                continue
            self._time.sleep(_RESET_RETRY_SETTLE_SECONDS)
            return
        raise MicropythonTransportError(
            f"reset of {self.address} failed after "
            f"{_RESET_RETRY_ATTEMPTS} attempts: {last_error}",
        )

    def reset_into_bootloader(self) -> bool:
        """Issue ``machine.bootloader()`` to drop into the UF2 bootloader.

        Whether the call actually puts the chip in bootloader mode
        depends on the board's MicroPython build.  RP2040 / RP2350
        ports wire ``machine.bootloader()`` to the native UF2 ROM
        bootloader and it just works.  Other ports may not implement
        the function at all, or may implement it as a plain reset
        that boots straight back into the app.  We try blindly
        rather than maintain a board / firmware-version table: a
        successful entry surfaces as a new ROM-bootloader serial
        port visible to whatever polls for one, and an unsuccessful
        entry surfaces as no-new-port.  Don't add board-specific
        branching here: firing ``machine.bootloader()`` blindly and
        letting the caller's drive-poll be the success signal handles
        every port the same way.
        """
        try:
            self._ensure_serial()
            try:
                self._serial.exec_raw(
                    "import machine\nmachine.bootloader()\n", timeout=5,
                )
            except Exception:
                # Reset drops the serial link before a clean response
                # comes back, which is expected on success.  We can't
                # easily distinguish that from "bootloader attr missing"
                # here, so trust the exec_raw fired and let the caller's
                # drive-poll be the authoritative signal.
                pass
        except Exception:
            return False
        return True

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata.

        Opens the persistent raw REPL if needed and runs a short inline
        script.  No staging required because ``sys.implementation`` is a
        built-in attribute.  Failures are swallowed (``None`` returned)
        so a flaky or unusual firmware never blocks the real test run.

        Returns:
            :class:`DeviceImplementation` on success, or ``None`` if the
            probe could not complete or its output did not contain the
            expected marker line.
        """
        try:
            self._ensure_serial()
            result = self._serial.exec_raw(
                PROBE_IMPLEMENTATION_SCRIPT, timeout=10,
            )
        except Exception:  # pragma: no cover - hardware-only error paths
            return None
        return parse_probe_output(_decode_exec_result(result))

    def disconnect(self) -> None:
        """Clean up staging directory and close the persistent serial transport."""
        self._close_serial()
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        follow: Literal["exec", "soft_reboot"] = "exec",
        clean: bool = False,
    ) -> str:
        """Write *files* onto the device and execute *entrypoint*.

        In **mount mode**, the file tree is staged host-side, mounted
        through the persistent raw REPL, and the entrypoint runs from
        the mount point.  In **copy mode**, the staging tree is pushed
        to flash via ``mpremote fs cp -r`` and the entrypoint runs in
        whichever follow mode *follow* selects.

        Args:
            files: On-device-path -> bytes mapping.  Leading slashes
                are stripped before joining with the staging dir or
                device root.
            entrypoint: On-device path, must be a key of *files*.
            on_file_staged: Per-file callback invoked with the
                on-device path as each file is written to staging.
            on_execute_line: Callback invoked once per output line, in
                order, after execution completes.
            follow: Selects how the entrypoint runs.

                ``"exec"`` (default) wraps the entrypoint in an
                ``exec(open(...).read())`` bootstrap and runs it via
                ``self._serial.exec_raw`` with an inter-byte idle
                timeout.  Captures full stdout once the script returns
                and the raw REPL emits its EOF (``\\x04``) marker.
                Right for return-bounded scripts, hangs forever on
                ``while True`` bodies.

                ``"soft_reboot"`` sends ``Ctrl-B + Ctrl-D`` and lets
                MicroPython auto-run ``/main.py``, then reads serial
                output up to :attr:`timeout` seconds (returning
                partial output for infinite-loop bodies).  Requires
                copy mode with ``/main.py`` as the entrypoint, since
                MicroPython only auto-runs boot paths on flash.
            clean: Copy mode only.  When ``True``, wipe the device's
                ``/lib`` tree before pushing.  Top-level user files
                (``boot.py``, ``main.py``, ``settings.toml``) live
                outside ``/lib`` and survive.

        Returns:
            Combined stdout captured from the entrypoint execution.
            For ``follow="soft_reboot"`` and an infinite-loop body,
            this is whatever accumulated up to *self.timeout*.

        Raises:
            MicropythonTransportError: ``follow="soft_reboot"`` was
                requested with mount mode or with an entrypoint other
                than ``/main.py``.
        """
        validate_entrypoint_in_files(
            files, entrypoint, error_cls=MicropythonTransportError,
        )

        if follow == "soft_reboot":
            if self.mode != "copy":
                raise MicropythonTransportError(
                    "follow='soft_reboot' requires mode='copy'; got "
                    f"mode={self.mode!r}.  The soft-reboot pattern auto-runs "
                    "/main.py from flash, and mount mode (mpremote mount_local) "
                    "lands files at /remote and the runtime won't auto-run "
                    "them on soft-reboot."
                )
            if entrypoint.lstrip("/") != "main.py":
                raise MicropythonTransportError(
                    "follow='soft_reboot' requires entrypoint '/main.py'; "
                    f"got {entrypoint!r}.  MicroPython auto-runs /main.py "
                    "(after /boot.py) on soft-reboot, so other entrypoint "
                    "names won't run automatically."
                )

        if self._staging_dir is not None:
            self._staging_dir.cleanup()
        self._drop_active_mount()

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_deploy_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        write_files_to_staging(staging_path, files, on_file_staged)

        # Strip docstrings and comments from every staged .py before the
        # transfer so the board carries code, not prose.
        minify_python_tree(staging_path)
        relative_entrypoint = entrypoint.lstrip("/")
        if self.mode == "copy":
            # Copy mode pushes files to the device's real filesystem,
            # so on-device paths start at ``/`` as written.  MP does
            # not include /lib on sys.path by default; add it so a
            # callers' ``from helper import x`` resolves without
            # boilerplate.
            self._close_serial()
            if clean:
                # Clean push: clear the whole device root (only the
                # keep set survives), then the ``fs cp -r`` below
                # repopulates the payload.  A board ``settings.toml``
                # is evicted like everything outside the keep set.
                self._clean_slate_device()
            self._run_mpremote([
                "fs", "cp", "-r",
                str(staging_path) + "/.",
                ":",
            ])
            self._ensure_serial()
            entrypoint_on_device = f"/{relative_entrypoint}"
            sys_path_prefix = "import sys\nsys.path.insert(0, '/lib')\n"
        else:
            # mpremote mount_local mounts the staging dir at /remote
            # (not /), so entrypoint paths the caller wrote as
            # ``/main.py`` resolve to ``/remote/main.py`` on device.
            # Add /remote and /remote/lib to sys.path so relative
            # imports inside the user's code work the same way they
            # do in copy mode.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True
            entrypoint_on_device = f"/remote/{relative_entrypoint}"
            sys_path_prefix = (
                "import sys\n"
                "sys.path.insert(0, '/remote/lib')\n"
                "sys.path.insert(0, '/remote')\n"
            )

        if follow == "soft_reboot":
            # Caller validated mode == "copy" + entrypoint == "/main.py"
            # at the top.  Files are now on flash; the persistent
            # serial connection is open in raw REPL.  Hand off to the
            # soft-reboot read.
            try:
                output = self._trigger_soft_reboot_and_read()
            except Exception as error:
                raise MicropythonTransportError(
                    f"Device deploy soft-reboot read failed: {error}"
                ) from error
            # Leave the board in friendly REPL with main.py running.
            # Subsequent transport ops re-enter raw REPL on demand via
            # _ensure_serial; disconnect tolerates either REPL state.
            if on_execute_line is not None:
                for output_line in output.splitlines():
                    on_execute_line(output_line)
            return output

        script = f"{sys_path_prefix}exec(open({entrypoint_on_device!r}).read())"
        output = self._exec_or_classify(
            script,
            timeout=_EXECUTE_IDLE_TIMEOUT,
            failure_context="Device deploy-execute failed",
        )
        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self, *, clean_slate: bool = False) -> list[str]:
        """Implements the contract on :meth:`TransportProtocol.list_files_in_scope`.

        Copy mode dispatches the on-device walk via raw REPL
        (:data:`._device_scripts.LIST_ALL_SCRIPT` for
        ``clean_slate=True``, :data:`._device_scripts.LIST_SCOPE_SCRIPT`
        otherwise).  Mount mode (RAM) returns an empty list.

        Raises :class:`MicropythonTransportError` on raw-REPL failure.
        """
        if self.mode != "copy":
            return []
        self._drop_active_mount()
        script = LIST_ALL_SCRIPT if clean_slate else LIST_SCOPE_SCRIPT
        output = self._exec_or_classify(
            script,
            timeout=_INTERACTIVE_OP_TIMEOUT,
            failure_context="list_files_in_scope failed",
        )
        listed = parse_scope_listing(output)
        if not clean_slate:
            return listed
        keep = set(DEVICE_KEEP_SET)
        return [
            path for path in listed
            if not any(part.startswith(".") for part in path.split("/") if part)
            and path.rsplit("/", 1)[-1] not in keep
        ]

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* and reap directories that become empty.

        No-op in mount (RAM) mode, because mount mode doesn't write to
        flash, so there's nothing to delete.  Otherwise sends a
        small script that calls ``os.remove`` on each path then walks
        the whole filesystem bottom-up and ``os.rmdir``-reaps any
        directory that's now empty; missing paths and per-path errors
        are tolerated silently so the diff-cleanup pass never blocks
        the actual deploy.

        The reap is load-bearing on MicroPython: ``os.remove`` drops
        files but never their parent directory, and MP's default
        ``sys.path`` is ``['', '.frozen', '/lib']`` with ``''`` (root)
        FIRST.  An empty root-level ``/<pkg>/`` resolves
        ``import <pkg>`` to a PEP 420 namespace package (``__file__``
        is ``None``, ``dir()`` empty) and shadows the populated
        ``/lib/<pkg>/`` deeper in the path.  ``rmdir`` only removes
        an empty directory so live packages are never touched.
        Dot-prefixed entries are skipped: they're not ours to reap.
        """
        if not paths:
            return
        if self.mode != "copy":
            return
        self._drop_active_mount()
        self._exec_or_classify(
            delete_files_script(paths),
            timeout=_INTERACTIVE_OP_TIMEOUT,
            failure_context="delete_files failed",
        )

    def clear_entrypoints(self) -> None:
        """Remove ``main.py`` / ``code.py`` and confirm they are gone.

        Copy mode only.  Mount (RAM) mode never writes a persistent
        entrypoint.  Runs ``os.remove`` *on the device* (authoritative
        immediately, since unlike the CIRCUITPY host-FAT path there is
        no flush lag) and, in the same raw-REPL script, re-``stat``s each
        path so a still-present entrypoint raises on the device and
        surfaces as a loud error.  Call once before a soft-reset so
        the reboot cannot race a stale entrypoint left by a prior
        deploy.
        """
        if self.mode != "copy":
            return
        self._drop_active_mount()
        self._exec_or_classify(
            CLEAR_ENTRYPOINTS_SCRIPT,
            timeout=_INTERACTIVE_OP_TIMEOUT,
            failure_context="clear_entrypoints failed",
        )

    def wipe_filesystem(self) -> None:
        """Implements the contract on :meth:`TransportProtocol.wipe_filesystem`.

        Dispatches :data:`_WIPE_FILESYSTEM_SCRIPT` as a one-shot
        ``mpremote exec`` subprocess rather than over the persistent
        :class:`SerialTransport`: ``machine.soft_reset()`` clears
        interpreter state and the ``raw_repl`` framing, so reusing the
        persistent transport across the reset would leave it in an
        inconsistent state.  After the subprocess returns, the serial
        port is given :data:`_WIPE_REBOOT_SETTLE_SECONDS` to settle so
        the next :meth:`connect` / :meth:`stage` call sees a fully
        booted runtime ready to accept a fresh raw-REPL session.
        """
        if self.mode != "copy":
            return
        # Drop any active mount + persistent transport so the subprocess
        # below can claim the serial port.  The soft_reset inside the
        # script invalidates the raw-REPL framing on whatever transport
        # owns the port at the time, so we deliberately don't try to
        # reuse the persistent transport across the call.
        self._drop_active_mount()
        self._close_serial()
        try:
            self._run_mpremote(["exec", WIPE_FILESYSTEM_SCRIPT])
        except MicropythonTransportError as error:
            raise MicropythonTransportError(
                f"wipe_filesystem failed: {error}",
            ) from error
        # Settle the runtime on the freshly-formatted volume before any
        # follow-up port grab; see _WIPE_REBOOT_SETTLE_SECONDS for why.
        self._time.sleep(_WIPE_REBOOT_SETTLE_SECONDS)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_serial(self) -> None:
        """Open the persistent serial transport and enter raw REPL if needed."""
        if self._serial is not None:
            return
        self._serial = self._transport_factory(self.address, self.baudrate)
        self._serial.enter_raw_repl(soft_reset=True)

    def _drop_active_mount(self) -> None:
        """Umount the live staging mount, if any (best-effort).

        Every flash-touching op and every serial handoff must drop the
        mount first: mpremote's ``mount_local`` wraps the serial in a
        ``SerialIntercept`` that must be unwrapped before the port is
        reused, and the device-side mount hook refuses to replace a
        live mount (``EPERM``).  No-op when nothing is mounted or the
        serial is already gone.
        """
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False

    def _exec_or_classify(
        self, script: str, *, timeout: float, failure_context: str,
    ) -> str:
        """Run *script* over the persistent raw REPL, classifying failure.

        Opens the serial transport if needed, then ``exec_raw``s the
        script.  Any failure is re-raised as a
        :class:`MicropythonTransportError` whose message starts with
        *failure_context*.  These prefixes are load-bearing:
        :func:`chumicro_deploy.recovery.classify_deploy_failure`
        pattern-matches them, so pass the existing per-op wording, not
        new phrasing.

        Args:
            script: Self-contained Python source to run on the device.
            timeout: Inter-byte idle timeout for the script's output.
            failure_context: Message prefix for the classified error.

        Returns:
            Decoded stdout (stderr appended) from the device.
        """
        self._ensure_serial()
        try:
            result = self._serial.exec_raw(script, timeout=timeout)
        except Exception as error:
            raise MicropythonTransportError(
                f"{failure_context}: {error}"
            ) from error
        return _decode_exec_result(result)

    def _trigger_soft_reboot_and_read(self) -> str:
        """Exit raw REPL, soft-reboot, read main.py output, return user text.

        Handles ``main.py`` bodies that never return (a ``while True``
        loop) by reading serial directly with a wall-clock timeout
        instead of waiting for the raw-REPL EOF marker.  The raw-REPL
        ``exec_raw`` path (``follow="exec"``) works for return-bounded
        scripts because raw REPL emits the EOF (``\\x04``) marker when
        the script returns; for an infinite-loop body the EOF never
        fires and the deploy hangs.  Soft-reboot bypasses raw REPL and
        returns whatever serial output accumulated before the timeout.

        Sequence:

        1. Send ``\\r\\x02`` (Ctrl-B) to exit raw REPL into friendly REPL.
        2. Send ``\\x04`` (Ctrl-D) to soft-reboot.  MicroPython prints
           ``MPY: soft reboot``, runs ``boot.py`` (if present), then
           auto-runs ``/main.py``.
        3. Read serial bytes via ``mpremote.SerialTransport.read_until``
           with ``ending=b"\\r\\n>>> "`` (the friendly-REPL prompt, which
           is the end-of-execution marker).  ``timeout_overall=self.timeout``
           bounds the wait, and for ``while True`` bodies the prompt
           never appears and the read returns whatever accumulated.

        Returns:
            User stdout from ``main.py`` execution, with the
            ``MPY: soft reboot`` start marker, friendly-REPL banner,
            and ``>>>`` prompt stripped.  See
            :meth:`_extract_main_py_output` for the trimming rules.
        """
        assert self._serial is not None
        port = self._serial.serial
        # Two-stage transition.  Ctrl-B + Ctrl-D back-to-back races the
        # firmware: it can still be finishing the raw-REPL exit and miss
        # Ctrl-D as "soft-reboot from friendly REPL".  Wait for the
        # friendly-REPL prompt before issuing Ctrl-D so the transition
        # is observable.
        port.write(b"\r\x02")
        self._serial.read_until(
            1, b">>> ", timeout=2.0, timeout_overall=2.0,
        )
        port.write(b"\x04")
        # Long inter-byte timeout (we don't care about idle gaps within
        # main.py output, only the overall budget); ``timeout_overall``
        # caps the total wait.
        raw = self._serial.read_until(
            1, b"\r\n>>> ",
            timeout=self.timeout,
            timeout_overall=self.timeout,
        )
        return self._extract_main_py_output(raw)

    @staticmethod
    def _extract_main_py_output(raw_boot_output: bytes) -> str:
        """Extract user output from a fresh-boot serial capture.

        Sync to the ``MPY: soft reboot`` start marker so any pre-reboot
        bytes still in the host's serial buffer are discarded.  Strip
        the trailing friendly-REPL banner (``MicroPython v...; <board>``
        line + ``Type "help()" for more information.`` line + ``>>> ``
        prompt) when ``main.py`` returned cleanly.  When ``main.py`` is
        a ``while True`` body the read times out without those markers
        and the trim is a no-op, so partial accumulated output is
        returned verbatim.

        Tracebacks are kept (they're diagnostic for the user); only
        the post-traceback REPL banner is stripped.

        Args:
            raw_boot_output: Bytes captured from the soft-reboot read.
        """
        text = raw_boot_output.decode("utf-8", errors="replace")
        marker_index = text.find("MPY: soft reboot")
        if marker_index != -1:
            trailing_newline = text.find("\n", marker_index)
            if trailing_newline != -1:
                text = text[trailing_newline + 1:]
        # Trim trailing friendly-REPL output.  Two anchors, whichever
        # appears first wins:
        #   * ``\nMicroPython v``, the start of the friendly-REPL banner
        #     line (``MicroPython v1.28.0 on ...; <board>``).  Cuts
        #     before the banner so any preceding traceback is
        #     preserved.  Hits on every clean return or exception.
        #   * ``\n>>> `` (or bare ``>>> `` at start), the friendly-REPL
        #     prompt.  Backstop for cases where the banner wasn't
        #     captured (e.g. a quick return whose banner straddled
        #     the read window).  Without this, the trailing prompt
        #     leaks into the returned text.
        candidates: list[int] = []
        for anchor in ("\nMicroPython v", "\n>>> "):
            position = text.find(anchor)
            if position != -1:
                candidates.append(position)
        if text.startswith(">>> "):
            candidates.append(0)
        if candidates:
            text = text[:min(candidates)]
        return text.strip("\r\n") + "\n"

    def _close_serial(self) -> None:
        """Close the persistent serial transport if open."""
        if self._serial is None:
            return
        try:
            self._drop_active_mount()
            try:
                self._serial.exit_raw_repl()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._serial.close()
        finally:
            self._serial = None

    def _clean_slate_device(self) -> None:
        """Clean-slate the device root, preserving only the keep set.

        Reconciles a board left dirty by a prior run without destroying
        the keep set.  ``mpremote fs cp`` never deletes, so without
        this each deploy stacks onto the previous tree until the LFS
        partition fills up.
        Every root entry except the keep set (``boot.py`` /
        ``boot_out.txt`` / ``_chu_kv.msgpack``) is removed
        recursively; the subsequent ``fs cp -r`` repopulates the
        payload.  A board ``settings.toml`` is *not* in the keep set
        and is evicted: its wifi credentials would compete with the
        runtime config we deploy.

        One device-side script, one round trip, best-effort per entry.
        A hard failure here would mask the staging it precedes.
        """
        script = clean_slate_script(DEVICE_KEEP_SET)
        try:
            # mpremote subprocess (not the persistent serial): the
            # serial is closed at entry and the `fs cp` that follows is
            # also a subprocess.  Opening the serial here would hold the
            # port and fail that push.
            self._run_mpremote(["exec", script])
        except MicropythonTransportError:  # pragma: no cover -best-effort
            # A clean device (nothing to remove) or a transient
            # hiccup: the post-`fs cp` free-space check is the real
            # guard, so don't let this mask the staging it precedes.
            pass

    def _remove_device_entries(self, entries: list[str]) -> None:
        """Recursively remove top-level *entries* from the device root.

        ``mpremote fs cp`` never deletes, so the prior library's
        staged tree must be cleared or a multi-library sweep fills the
        device LittleFS.  One device-side script (one round trip,
        authoritative) ``rmtree``s each entry, tolerating already-
        absent paths.  Best-effort: a stray leftover is cleaned by the
        next switch and the post-``fs cp`` free space is the real
        guard.  A hard failure here would mask the staging operation
        it precedes.
        """
        try:
            self._run_mpremote(["exec", remove_entries_script(entries)])
        except MicropythonTransportError:  # pragma: no cover - hardware-only
            # Leftovers are reclaimed on the next switch; never let a
            # cleanup error stand in for the real staging result.
            pass

    def _run_mpremote(self, arguments: list[str]) -> subprocess.CompletedProcess:
        """Run an mpremote command and return the result.

        Args:
            arguments: Arguments to pass after ``mpremote connect <address>``.

        Raises:
            MicropythonTransportError: If the command exits non-zero, or
                runs past ``_MPREMOTE_SUBPROCESS_TIMEOUT``.  A board whose
                USB-CDC wedged mid-command would otherwise hang the deploy
                forever.
        """
        command = [_resolve_mpremote_binary(), "connect", self.address] + arguments
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=_MPREMOTE_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as timeout_error:
            raise MicropythonTransportError(
                f"mpremote command timed out after "
                f"{_MPREMOTE_SUBPROCESS_TIMEOUT:.0f} s; the board's USB-CDC "
                f"likely wedged mid-command.\n"
                f"  command: {' '.join(command)}\n"
                f"  Fix: replug the board, or run "
                f"`chumicro-workspace reset-board --yes` to wipe and re-prep it."
            ) from timeout_error
        if result.returncode != 0:
            raise MicropythonTransportError(
                f"mpremote command failed (exit {result.returncode}):\n"
                f"  command: {' '.join(command)}\n"
                f"  stderr: {result.stderr.strip()}"
            )
        return result

    def _copy_tree(self, source: Path, destination: Path) -> None:
        """Recursively copy a directory tree into the destination.

        Copies top-level packages (directories with ``__init__.py``)
        from *source* into *destination*, preserving the package
        directory structure.

        Skips host-only build artifacts that have no business on a
        device: CPython bytecode caches (``__pycache__``, ``*.pyc``),
        editable-install metadata (``*.egg-info``), and other VCS /
        tooling dirs.

        Also drops ``.py`` files whose ``__chumicro_runtimes__`` marker
        excludes MicroPython, so a wrong-runtime adapter (e.g. ``cp.py``)
        never lands on the MP device.

        Args:
            source: Source directory to copy from (e.g. a ``src/`` dir).
            destination: Destination directory to copy into.
        """
        if not source.is_dir():
            return
        for child in sorted(source.iterdir()):
            if self._should_exclude_from_stage(child):
                continue
            target = destination / child.name
            if child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                self._copy_tree(child, target)
            elif child.is_file():
                target.write_bytes(child.read_bytes())

    def _should_exclude_from_stage(self, path: Path) -> bool:
        """Return True if *path* is host-only cruft that shouldn't deploy."""
        name = path.name
        if name in _STAGE_EXCLUDED_NAMES:
            return True
        if name.endswith(".pyc") or name.endswith(".egg-info"):
            return True
        if path.is_file() and path.suffix == ".py" and not file_targets_runtime(
            path, target_runtime=self._target_runtime,
        ):
            return True
        if (
            path.is_file()
            and path.suffix == ".py"
            and is_test_support_module(path)
            and not self._include_test_support
        ):
            # Test-support fakes are excluded unless explicitly opted in.
            return True
        return False
