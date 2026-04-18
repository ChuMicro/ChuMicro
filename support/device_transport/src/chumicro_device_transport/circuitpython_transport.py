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

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from chumicro_abstractions import RealTime

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
            Required when ``mode="flash"``.
        serial_port_factory: Callable that creates a serial port object.
            Accepts ``(port, baudrate, timeout)`` keyword arguments.
            Defaults to ``serial.Serial``.  Inject a fake for testing.
        time: Object providing ``monotonic()`` and ``sleep()`` methods.
            Defaults to ``RealTime`` from ``chumicro_abstractions``.
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
        time: RealTime | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self.mode = mode
        self.circuitpy_drive_path = circuitpy_drive_path
        self._serial_port_factory: Callable[..., object] = (
            serial_port_factory or self._default_serial_factory
        )
        self._time: RealTime = time or RealTime()
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
        """Copy staged files to the CIRCUITPY USB drive.

        Disables autoreload before copying to prevent restarts during
        the file transfer.

        Args:
            source_dirs: Library ``src/`` directories.
            test_files: Test files to deploy.
            harness_source: Path to the test harness ``src/`` directory.

        Raises:
            CircuitpythonTransportError: If ``circuitpy_drive_path`` is
                not configured or the drive path does not exist.
        """
        if not self.circuitpy_drive_path:
            raise CircuitpythonTransportError(
                "circuitpy_drive_path is required for flash mode"
            )
        drive_path = Path(self.circuitpy_drive_path)
        if not drive_path.is_dir():
            raise CircuitpythonTransportError(
                f"CIRCUITPY drive not found: {drive_path}"
            )

        # Disable autoreload to prevent restarts during file copy.
        self._send_repl_command(
            "import supervisor; "
            "supervisor.runtime.autoreload = False"
        )

        # Copy library packages to lib/ on the drive.
        lib_destination = drive_path / "lib"
        lib_destination.mkdir(exist_ok=True)

        for source_directory in source_dirs:
            self._copy_packages_to_drive(source_directory, lib_destination)

        # Copy harness packages to lib/.
        self._copy_packages_to_drive(harness_source, lib_destination)

        # Copy test files to drive root.
        for test_file in test_files:
            destination = drive_path / test_file.name
            shutil.copy2(test_file, destination)

    @staticmethod
    def _copy_packages_to_drive(
        source_directory: Path,
        lib_destination: Path,
    ) -> None:
        """Copy top-level packages from a source directory to the drive.

        Args:
            source_directory: A ``src/`` directory containing packages.
            lib_destination: The ``lib/`` directory on the CIRCUITPY drive.
        """
        if not source_directory.is_dir():
            return
        for child in sorted(source_directory.iterdir()):
            if not child.is_dir():
                continue
            init_file = child / "__init__.py"
            if not init_file.exists():
                continue
            target = lib_destination / child.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)

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

        Args:
            directory: Directory to walk.
            dotted_prefix: Dotted module name prefix for this directory.
        """
        assert self._staged_sources is not None
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
                    module_name = dotted_prefix
                else:
                    module_name = f"{dotted_prefix}.{child.stem}"
                source_text = child.read_text(encoding="utf-8")
                self._staged_sources.append((module_name, source_text))

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

        In flash mode, re-enables autoreload and triggers a reload
        before closing the port.
        """
        if self._port is not None:
            if self.mode == "flash":
                try:
                    self._send_repl_command(
                        "import supervisor; "
                        "supervisor.runtime.autoreload = True; "
                        "supervisor.reload()"
                    )
                except Exception:  # pragma: no cover
                    pass  # Best-effort restore.
            try:
                self._port.close()
            except Exception:  # pragma: no cover
                pass  # Best-effort close.
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

