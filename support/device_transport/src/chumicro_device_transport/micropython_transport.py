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

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - type-only
    from mpremote.transport_serial import SerialTransport


class MicropythonTransportError(Exception):
    """Raised when an mpremote command fails."""


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

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage.
            harness_source: Path to the test harness ``src/`` directory.
        """
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
        # mpremote's exec_raw returns (stdout_bytes, stderr_bytes).  Merge
        # them so tracebacks surface in the captured output that
        # ``result_parser.parse_output`` sees.
        if isinstance(result, tuple):
            stdout_bytes, stderr_bytes = result
            stdout = (
                stdout_bytes.decode("utf-8", errors="replace")
                if stdout_bytes else ""
            )
            stderr = (
                stderr_bytes.decode("utf-8", errors="replace")
                if stderr_bytes else ""
            )
            return stdout + stderr
        if isinstance(result, bytes):
            return result.decode("utf-8", errors="replace")
        return result

    def soft_reset(self) -> None:
        """Soft-reset the device to clear interpreter state.

        Re-enters the raw REPL with ``soft_reset=True`` if the persistent
        transport is open; otherwise subprocess ``mpremote reset``.  Used
        between test groups so each group starts with a clean
        interpreter.
        """
        if self._serial is not None:
            try:
                self._serial.exit_raw_repl()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            # Re-enter with soft_reset=True so sys.modules / heap clear.
            self._serial.enter_raw_repl(soft_reset=True)
            # If we had a mount, restore it.
            if self._mounted and self._staging_path is not None:
                self._serial.mount_local(str(self._staging_path))
        else:
            self._run_mpremote(["reset"])

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

    def disconnect(self) -> None:
        """Clean up staging directory and close the persistent serial transport."""
        self._close_serial()
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

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
        command = ["mpremote", "connect", self.address] + arguments
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
