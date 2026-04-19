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

import os
import shutil
import subprocess
import sys as _sys_module
import tempfile
import time as _time_module
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

_CTRL_A = b"\x01"
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

#: Volume name CircuitPython uses by default.
_CIRCUITPY_VOLUME_NAME = "CIRCUITPY"


def find_circuitpy_drive() -> str | None:
    """Auto-detect the CIRCUITPY USB drive mount path.

    Checks common mount locations on macOS and Linux.  Returns the
    first path that exists as a directory, or ``None`` if no drive
    is found.

    Checked locations (in order):

    - macOS: ``/Volumes/CIRCUITPY``
    - Linux: ``/media/<user>/CIRCUITPY``
    - Linux (systemd): ``/run/media/<user>/CIRCUITPY``
    """
    username = os.environ.get("USER", "")
    candidates = [
        Path("/Volumes") / _CIRCUITPY_VOLUME_NAME,
        Path("/media") / username / _CIRCUITPY_VOLUME_NAME,
        Path("/run/media") / username / _CIRCUITPY_VOLUME_NAME,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    return None


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


class CircuitpythonTransportError(Exception):
    """Raised when a CircuitPython serial operation fails."""


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
        time: object | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self.mode = mode
        self.circuitpy_drive_path = circuitpy_drive_path
        self._serial_port_factory: Callable[..., object] = (
            serial_port_factory or self._default_serial_factory
        )
        self._time = time or _time_module
        self._port: SerialPort | None = None
        self._staged_sources: list[tuple[str, str]] | None = None

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
    ) -> None:
        """Read source files into memory for inline execution.

        In RAM mode, source code is read and stored for embedding into
        the bootstrap code block sent via raw REPL.

        In flash mode, source packages are copied to the CIRCUITPY USB
        drive after disabling autoreload.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage (stored for bootstrap
                generation).
            harness_source: Path to the test harness ``src/`` directory.
        """
        self._staged_sources = []
        # Collect library package sources (needed for both modes).
        for source_directory in source_dirs:
            self._collect_package_sources(source_directory)
        # Collect harness sources.
        self._collect_package_sources(harness_source)

        if self.mode == "flash":
            self._stage_to_flash(source_dirs, test_files, harness_source)

    def _stage_to_flash(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
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

        # Prevent macOS Spotlight from indexing the drive — it creates
        # hidden metadata files and slows down FAT32 writes.
        self._disable_spotlight_indexing(drive_path)

        # Disable autoreload to prevent restarts during file copy.
        self._send_repl_command(
            "import supervisor; "
            "supervisor.runtime.autoreload = False"
        )

        # Build a local staging directory that mirrors the full drive
        # layout, then rsync it to the device in one pass.
        with tempfile.TemporaryDirectory() as staging_directory:
            staging_path = Path(staging_directory)

            # lib/ — library packages + test harness.
            lib_staging = staging_path / "lib"
            lib_staging.mkdir()
            for source_directory in source_dirs:
                self._merge_packages(source_directory, lib_staging)
            self._merge_packages(harness_source, lib_staging)

            # Test files at root.
            for test_file in test_files:
                shutil.copy2(test_file, staging_path / test_file.name)

            # Strip macOS extended attributes from the staging dir
            # before rsyncing — xattrs cause slow FAT32 transfers and
            # generate ._ resource fork files.
            self._strip_extended_attributes(staging_path)

            self._rsync(staging_path, drive_path)

        # Remove ._ resource fork files that macOS may have created
        # on the FAT32 volume despite rsync's --exclude=._* flag.
        self._clean_dot_files(drive_path)

        # Flush the volume so the device reads current content.
        self._flush_volume(drive_path)

    @staticmethod
    def _merge_packages(
        source_directory: Path,
        staging_destination: Path,
    ) -> None:
        """Copy top-level packages from a source directory to a staging dir.

        Merges into the staging destination using ``dirs_exist_ok=True``
        so multiple source directories can contribute packages.  This
        operates on the local filesystem (not the USB drive), so
        ``shutil.copytree`` is reliable here.

        Args:
            source_directory: A ``src/`` directory containing packages.
            staging_destination: Local staging directory to merge into.
        """
        if not source_directory.is_dir():
            return
        for child in sorted(source_directory.iterdir()):
            if not child.is_dir():
                continue
            init_file = child / "__init__.py"
            if not init_file.exists():
                continue
            target = staging_destination / child.name
            shutil.copytree(
                child,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )

    @staticmethod
    def _rsync(source: Path, destination: Path) -> None:
        """Rsync a source directory's contents to a destination.

        Uses ``--checksum`` to verify content (FAT32 timestamps are
        unreliable), ``--inplace`` to write directly into files (avoids
        temp-file rename races on FAT32), and ``--delete`` to remove
        stale files from the destination.

        Device config files and build artifacts that live on the drive
        but are not part of the test deployment are excluded from
        deletion.

        Raises:
            CircuitpythonTransportError: If rsync is not installed or
                the sync fails.

        Args:
            source: Source directory whose contents to sync.
            destination: Destination directory.
        """
        command = [
            "rsync",
            "--recursive",
            "--checksum",
            "--inplace",
            "--delete",
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=.DS_Store",
            "--exclude=._*",
            "--exclude=boot.py",
            "--exclude=boot_out.txt",
            "--exclude=code.py",
            "--exclude=settings.toml",
            str(source) + "/",
            str(destination) + "/",
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, check=True)
        except FileNotFoundError as not_found_error:
            raise CircuitpythonTransportError(
                "rsync is required for flash deploy mode but was not found.  "
                "Install rsync and ensure it is on your PATH."
            ) from not_found_error
        except subprocess.CalledProcessError as rsync_error:
            raise CircuitpythonTransportError(
                f"rsync failed: {rsync_error.stderr}"
            ) from rsync_error


    @staticmethod
    def _flush_volume(drive_path: Path) -> None:
        """Flush pending writes to the volume containing *drive_path*.

        On macOS, calls the ``sync`` command; on other platforms, uses
        ``os.sync()``.  Always waits briefly afterward to let the USB
        controller finish writing to FAT32 media.

        Args:
            drive_path: Path on the volume to flush.
        """
        if _sys_module.platform == "darwin":
            try:
                subprocess.run(["sync"], check=True, capture_output=True)
            except Exception:  # pragma: no cover
                print("WARNING: sync command failed — falling back to os.sync()")
                os.sync()
        else:
            os.sync()  # pragma: no cover — tests run on macOS

        # Allow time for the USB controller to finish writing to the
        # FAT32 media.  Without this pause, the device may read stale
        # content even after sync returns.
        _time_module.sleep(0.5)

    @staticmethod
    def _strip_extended_attributes(path: Path) -> None:
        """Remove macOS extended attributes from all files under *path*.

        Extended attributes (xattrs) cause slow transfers to FAT32
        volumes and generate ``._`` resource fork files.  Stripping
        them from the staging directory before rsync prevents these
        artifacts from reaching the device.

        No-op on non-macOS platforms.

        Args:
            path: Root directory to strip recursively.
        """
        if _sys_module.platform != "darwin":
            return  # pragma: no cover — tests run on macOS
        try:
            subprocess.run(
                ["xattr", "-cr", str(path)],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            print("WARNING: xattr not found — skipping extended attribute removal")

    @staticmethod
    def _clean_dot_files(drive_path: Path) -> None:
        """Merge or remove ``._`` resource fork files on a FAT32 volume.

        macOS creates ``._`` files on FAT32 drives even when rsync
        excludes them, because the OS itself writes them during
        filesystem operations.  ``dot_clean`` merges these back into
        the native file or removes them if the native file is absent.

        No-op on non-macOS platforms.

        Args:
            drive_path: Mount point of the FAT32 volume.
        """
        if _sys_module.platform != "darwin":
            return  # pragma: no cover — tests run on macOS
        try:
            subprocess.run(
                ["dot_clean", str(drive_path)],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            print("WARNING: dot_clean not found — skipping ._ file cleanup")

    @staticmethod
    def _disable_spotlight_indexing(drive_path: Path) -> None:
        """Disable Spotlight indexing on a mounted volume.

        Spotlight indexing creates ``.Spotlight-V100`` metadata and
        slows down FAT32 writes.  ``mdutil -i off`` is idempotent
        but resets on remount, so it is called each time the drive
        is used.

        May require elevated privileges on some macOS versions; if
        the command fails, indexing continues and no error is raised.

        No-op on non-macOS platforms.

        Args:
            drive_path: Mount point of the volume.
        """
        if _sys_module.platform != "darwin":
            return  # pragma: no cover — tests run on macOS
        try:
            subprocess.run(
                ["mdutil", "-i", "off", str(drive_path)],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            print("WARNING: mdutil not found — skipping Spotlight indexing disable")

    def _collect_package_sources(self, source_directory: Path) -> None:
        """Walk a source directory and collect all .py files as module entries.

        Each entry is ``(dotted_module_name, source_text)``.

        Args:
            source_directory: A ``src/`` directory containing packages.
        """
        if not source_directory.is_dir():
            return
        for package_directory in sorted(source_directory.iterdir()):
            if not package_directory.is_dir():
                continue
            init_file = package_directory / "__init__.py"
            if not init_file.exists():
                continue
            self._collect_package_files(
                package_directory,
                package_directory.name,
            )

    def _collect_package_files(
        self,
        directory: Path,
        dotted_prefix: str,
    ) -> None:
        """Recursively collect .py files from a package directory.

        Collects ``__init__.py`` last so that submodules are already
        registered in ``sys.modules`` when the package init executes
        relative imports.

        Args:
            directory: Directory to walk.
            dotted_prefix: Dotted module name prefix for this directory.
        """
        assert self._staged_sources is not None
        init_entry: tuple[str, str] | None = None
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                child_init = child / "__init__.py"
                if child_init.exists():
                    self._collect_package_files(
                        child,
                        f"{dotted_prefix}.{child.name}",
                    )
            elif child.suffix == ".py":
                if child.name == "__init__.py":
                    # Defer __init__.py until after submodules.
                    source_text = child.read_text(encoding="utf-8")
                    init_entry = (dotted_prefix, source_text)
                else:
                    module_name = f"{dotted_prefix}.{child.stem}"
                    source_text = child.read_text(encoding="utf-8")
                    self._staged_sources.append((module_name, source_text))
        # Append __init__.py last.
        if init_entry is not None:
            self._staged_sources.append(init_entry)

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
        if self._staged_sources is None:
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

    def reset(self) -> None:
        """Soft-reset the device via Ctrl-D."""
        if self._port is not None:
            self._port.write(_CTRL_D)
            # Allow time for the reset to complete.
            self._time.sleep(0.5)

    def disconnect(self) -> None:
        """Close the serial port and clear staged data.

        In flash mode, re-enters raw REPL (in case a reset or soft
        reboot exited it), then re-enables autoreload and triggers a
        reload before closing the port.
        """
        if self._port is not None:
            if self.mode == "flash":
                try:
                    self._enter_raw_repl()
                    self._send_repl_command(
                        "import supervisor; "
                        "supervisor.runtime.autoreload = True; "
                        "supervisor.reload()"
                    )
                except Exception as restore_error:
                    print(f"WARNING: Failed to restore autoreload on disconnect: {restore_error}")
            try:
                self._port.close()
            except Exception as close_error:  # pragma: no cover
                print(f"WARNING: Failed to close serial port on disconnect: {close_error}")
            self._port = None
        self._staged_sources = None

    @property
    def staged_sources(self) -> list[tuple[str, str]] | None:
        """Return the staged module sources, or None if not staged."""
        return self._staged_sources

    def _read_until(self, marker: bytes) -> bytes:
        """Read from serial until *marker* is found or timeout is reached.

        Args:
            marker: Byte sequence to look for.

        Returns:
            All bytes read, including the marker if found.
        """
        assert self._port is not None
        accumulated = b""
        deadline = self._time.monotonic() + self.timeout
        while self._time.monotonic() < deadline:
            waiting = self._port.in_waiting
            if waiting > 0:
                chunk = self._port.read(waiting)
                accumulated += chunk
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
