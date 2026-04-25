"""MicroPython device transport using mpremote.

Two execution paths:

- **Persistent serial transport** (mount mode and per-execute path):
  uses ``mpremote.transport_serial.SerialTransport`` directly — opens
  the serial port once per session, enters raw REPL once, mounts the
  staging directory once, and runs each bootstrap via ``exec_raw``.
  Eliminates the ~2-3 s cold-start cost of spawning ``mpremote`` per
  ``execute()`` call.
- **Subprocess fallback** (copy mode staging, reset/recover): uses the
  ``mpremote`` CLI for operations that are one-shot and easier to express
  via the CLI.  The serial port is closed before these calls and
  reopened on the next ``execute()``.

See Decision 0027 for the full transport protocol.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    parse_probe_output,
    validate_entrypoint_in_files,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    from mpremote.transport_serial import SerialTransport


class MicropythonTransportError(Exception):
    """Raised when an mpremote command fails."""


class MicropythonMidDeployDisconnected(MicropythonTransportError):
    """Raised when the device drops mid-deploy.

    Subclass so callers can ``except`` "the cable came out" without
    conflating it with other mpremote transport errors (mount
    failure, copy failure, bootstrap exec failed).  Mirrors
    :class:`CircuitpythonMidDeployDisconnected` and
    :class:`chumicro_repl.session.ReplSessionDisconnected`.

    The original :class:`OSError` is attached as :attr:`cause` so
    callers that need the underlying errno can read it without
    re-parsing :func:`str` of the wrapper.
    """

    def __init__(self, cause: OSError, context: str = "") -> None:
        prefix = f"device disconnected during {context}" if context else (
            "device disconnected"
        )
        super().__init__(f"{prefix}: {cause}")
        self.cause = cause


def _resolve_mpremote_binary() -> str:
    """Return the ``mpremote`` executable path to invoke via subprocess.

    ``mpremote`` is a ``requirements-dev.txt`` dependency, so it lands in
    ``.venv/bin/mpremote`` after workspace setup.  Shelling out with the
    bare name only works when ``.venv/bin`` is on ``PATH``
    (i.e. after ``source .venv/bin/activate``), which fails for direct
    ``.venv/bin/python scripts/run.py test-libraries-functional`` invocations and for
    IDE play buttons that launch via the interpreter path without an
    activated shell.

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
    land on stderr, so both streams are merged — callers downstream parse
    the combined output with ``result_parser.parse_output``.

    Args:
        result: Return value from ``exec_raw`` (tuple, bytes, or str).

    Returns:
        UTF-8 decoded text with stderr appended to stdout.
    """
    if isinstance(result, tuple):
        stdout_bytes, stderr_bytes = result
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        return stdout + stderr
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="replace")
    return result


def _default_transport_factory(address: str, baudrate: int) -> SerialTransport:
    """Default :class:`SerialTransport` factory.

    Importing inside the call so test environments that monkey-patch
    the factory don't need ``mpremote`` installed.

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
            persistent serial transport — subprocess ``mpremote``
            invocations negotiate baud rate themselves.
        mode: ``"mount"`` (default) or ``"copy"``.
        runner: Callable that executes subprocess commands.  Accepts
            the same signature as ``subprocess.run``.  Defaults to
            ``subprocess.run``.  Inject a fake for testing.
        transport_factory: Callable that builds a :class:`SerialTransport`
            given ``(address, baudrate)``.  Defaults to
            :func:`_default_transport_factory`.  Inject a fake to avoid
            opening real serial ports in tests.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        mode: str = "mount",
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        transport_factory: Callable[[str, int], Any] | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.mode = mode
        self._runner = runner or subprocess.run
        self._transport_factory = transport_factory or _default_transport_factory
        self._staging_dir: tempfile.TemporaryDirectory | None = None
        self._staging_path: Path | None = None
        self._serial: Any = None
        self._mounted: bool = False

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
    ) -> None:
        """Prepare a staging directory with library sources, tests, and harness.

        In mount mode, the staging directory is mounted on the device
        via the persistent serial transport.  In copy mode, it is
        recursively copied to flash via ``mpremote fs cp -r``.

        Safe to call repeatedly on the same transport (RAM-mode
        orchestration re-stages per file).  On re-stage in mount mode
        the existing mount is dropped first — otherwise mpremote's
        ``mount_local`` hits ``OSError: [Errno 1] EPERM`` because the
        device-side mount hook refuses to replace a live mount.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage.
            harness_source: Path to the test harness ``src/`` directory.
        """
        # Drop any mount/tempdir left from a prior stage() on this
        # transport so re-staging is idempotent.
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_device_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        # Copy source packages into staging.
        for source_dir in source_dirs:
            self._copy_tree(source_dir, staging_path)

        # Copy harness source.
        self._copy_tree(harness_source, staging_path)

        # Copy test files into staging root.
        for test_file in test_files:
            destination = staging_path / test_file.name
            destination.write_bytes(test_file.read_bytes())

        if self.mode == "copy":
            # Subprocess `fs cp -r` — release the serial port if held.
            self._close_serial()
            self._run_mpremote([
                "fs", "cp", "-r",
                str(staging_path) + "/.",
                ":",
            ])
        else:
            # Mount mode — open the persistent transport now and mount
            # the staging dir so every subsequent execute() reuses both.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True

    def execute(self, bootstrap_script: str) -> str:
        """Execute a bootstrap script on the device and return captured output.

        Uses the persistent serial transport's ``exec_raw`` so each call
        amortizes the one-time mpremote-cold-start cost.  In copy mode
        the serial transport is opened lazily (since ``stage()`` released
        it for the ``fs cp`` subprocess).

        Args:
            bootstrap_script: Python code to execute on the device.

        Returns:
            Captured stdout from the device.
        """
        if self._staging_path is None:
            raise MicropythonTransportError(
                "stage() must be called before execute()"
            )
        self._ensure_serial()
        try:
            result = self._serial.exec_raw(bootstrap_script, timeout=120)
        except Exception as error:
            raise MicropythonTransportError(
                f"Device exec failed: {error}"
            ) from error
        return _decode_exec_result(result)

    def soft_reset(self) -> None:
        """Soft-reset the device to clear interpreter state.

        Sends Ctrl-D through the persistent raw REPL.  This clears
        ``sys.modules`` and the device heap without toggling USB, so
        it is safe to run between every file.

        The mount is **not** restored by this method.  The caller (the
        device orchestration layer) always calls ``stage()`` next, and
        ``stage()`` owns the fresh mount.  Restoring the mount here
        instead would double-wrap mpremote's ``SerialIntercept``
        (``mount_local`` unconditionally wraps ``self.serial``) and
        garble subsequent I/O — that was the cause of the
        ``ImportError: no module named 'chumicro_test_harness'`` seen
        on the second file of an IDE folder run.

        Used between test groups so each group starts with a clean
        interpreter and an un-wrapped serial.  If no persistent
        transport is open, falls back to a subprocess ``mpremote
        reset``.
        """
        if self._serial is None:
            self._run_mpremote(["reset"])
            return

        # Umount while the device-side mount state is still live — after
        # Ctrl-D the ``os`` module and mount hook are gone and
        # ``umount_local`` would error when it tries to run
        # ``os.umount(...)``.  umount_local also unwraps the
        # SerialIntercept on the host side, which is required before
        # the next mount_local wraps again.
        if self._mounted:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False
        try:
            self._serial.exit_raw_repl()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        self._serial.enter_raw_repl(soft_reset=True)

    def reset(self) -> None:
        """Soft-reset the device.

        Used between library groups so each group starts with a clean
        interpreter.  Distinct from :meth:`recover` only in intent: this
        is a planned reset between healthy runs, while :meth:`recover` is
        called after a failed test when the board state is unknown.
        Both share :meth:`soft_reset`'s implementation.
        """
        self.soft_reset()

    def recover(self) -> None:
        """Attempt to recover after a failed test.

        Closes the persistent transport (if open) and reconnects from
        scratch — more aggressive than :meth:`soft_reset` because the
        previous failure might have left the raw REPL in an unknown
        state where ``exit_raw_repl`` itself could hang.
        """
        self._close_serial()
        # Subprocess reset so we don't immediately try to grab the port
        # again — mpremote handles the whole open/reset/close cycle.
        try:
            self._run_mpremote(["reset"])
        except MicropythonTransportError:  # pragma: no cover - hardware-only
            pass

    def reset_into_bootloader(self) -> bool:
        """Issue ``machine.bootloader()`` to drop into the UF2 bootloader.

        MicroPython's RP2040 + RP2350 ports implement
        ``machine.bootloader()`` — it resets the chip into the
        native UF2 ROM bootloader.  On ESP32 MicroPython builds the
        call typically raises ``AttributeError`` (no such function)
        and we return ``False`` so the flasher falls back to the
        manual-entry prompt; that's where esptool-based flows take
        over anyway.
        """
        try:
            self._ensure_serial()
            try:
                self._serial.exec_raw(
                    "import machine\nmachine.bootloader()\n", timeout=5,
                )
            except Exception:
                # Reset drops the serial link before a clean response
                # comes back — expected on success.  We can't easily
                # distinguish that from "bootloader attr missing" here,
                # so trust the exec_raw fired and let the caller's
                # drive-poll be the authoritative signal.
                pass
        except Exception:
            return False
        return True

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata.

        Opens the persistent raw REPL if needed and runs a short inline
        script — no staging required because ``sys.implementation`` is a
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
    ) -> str:
        """Write *files* onto the device and execute *entrypoint*.

        Mount mode writes the file tree to a host-side staging dir,
        mounts it through the persistent raw REPL, and execs the
        entrypoint from the mount point.  Copy mode writes to the
        host-side staging dir and uses ``mpremote fs cp -r`` to push
        to the device's flash, then execs via the persistent raw REPL.

        Args:
            files: On-device-path -> bytes mapping.  Paths may start
                with ``/``; the leading slash is stripped before
                joining with the staging dir / device root.
            entrypoint: On-device path (must be a key of *files*).
            on_file_staged: Per-file callback invoked with the
                on-device path as each file is written to staging.
            on_execute_line: Callback invoked once per line of the
                execute output (in order) after execution completes.

        Returns:
            Combined stdout captured from the entrypoint execution.
        """
        validate_entrypoint_in_files(
            files, entrypoint, error_cls=MicropythonTransportError,
        )

        if self._staging_dir is not None:
            self._staging_dir.cleanup()
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            self._mounted = False

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_deploy_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        for device_path in sorted(files.keys()):
            relative = device_path.lstrip("/")
            destination = staging_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(files[device_path])
            if on_file_staged is not None:
                on_file_staged(device_path)

        relative_entrypoint = entrypoint.lstrip("/")
        if self.mode == "copy":
            # Copy mode pushes files to the device's real filesystem,
            # so on-device paths start at ``/`` as written.  MP does
            # not include /lib on sys.path by default; add it so a
            # callers' ``from helper import x`` resolves without
            # boilerplate.
            self._close_serial()
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
            # imports inside the user's code work the same way copy
            # mode and CircuitPython flash mode do.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True
            entrypoint_on_device = f"/remote/{relative_entrypoint}"
            sys_path_prefix = (
                "import sys\n"
                "sys.path.insert(0, '/remote/lib')\n"
                "sys.path.insert(0, '/remote')\n"
            )

        script = f"{sys_path_prefix}exec(open({entrypoint_on_device!r}).read())"
        try:
            result = self._serial.exec_raw(script, timeout=120)
        except Exception as error:
            raise MicropythonTransportError(
                f"Device deploy-execute failed: {error}"
            ) from error
        output = _decode_exec_result(result)
        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_serial(self) -> None:
        """Open the persistent serial transport and enter raw REPL if needed."""
        if self._serial is not None:
            return
        self._serial = self._transport_factory(self.address, self.baudrate)
        self._serial.enter_raw_repl(soft_reset=True)

    def _close_serial(self) -> None:
        """Close the persistent serial transport if open."""
        if self._serial is None:
            return
        try:
            if self._mounted:
                try:
                    self._serial.umount_local()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass
                self._mounted = False
            try:
                self._serial.exit_raw_repl()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._serial.close()
        finally:
            self._serial = None

    def _run_mpremote(self, arguments: list[str]) -> subprocess.CompletedProcess:
        """Run an mpremote command and return the result.

        Args:
            arguments: Arguments to pass after ``mpremote connect <address>``.

        Raises:
            MicropythonTransportError: If the command exits with a non-zero code.
        """
        command = [_resolve_mpremote_binary(), "connect", self.address] + arguments
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MicropythonTransportError(
                f"mpremote command failed (exit {result.returncode}):\n"
                f"  command: {' '.join(command)}\n"
                f"  stderr: {result.stderr.strip()}"
            )
        return result

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        """Recursively copy a directory tree into the destination.

        Copies top-level packages (directories with ``__init__.py``)
        from *source* into *destination*, preserving the package
        directory structure.

        Args:
            source: Source directory to copy from (e.g. a ``src/`` dir).
            destination: Destination directory to copy into.
        """
        if not source.is_dir():
            return
        for child in sorted(source.iterdir()):
            target = destination / child.name
            if child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                MicropythonTransport._copy_tree(child, target)
            elif child.is_file():
                target.write_bytes(child.read_bytes())
