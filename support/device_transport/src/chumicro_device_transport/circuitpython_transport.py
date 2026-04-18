"""CircuitPython device transport using pyserial raw REPL.

Uses ``pyserial`` to connect to CircuitPython boards via serial and
execute code through raw REPL mode (Ctrl-A).  All library source, test
code, and the harness runner are sent inline as a single code block —
no file staging or flash writes required.

Raw REPL protocol:
1. Ctrl-C × 2 interrupts any running code.
2. Ctrl-A enters raw REPL (prompt: ``raw REPL; CTRL-B to exit\\r\\n>``).
3. Send code bytes, terminated with Ctrl-D.
4. Response: ``OK<stdout>\\x04<stderr>\\x04>``.

See Decision 0027 for the full transport protocol and CircuitPython
constraints.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

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


class CircuitpythonTransportError(Exception):
    """Raised when a CircuitPython serial operation fails."""


class CircuitpythonTransport:
    """Transport for CircuitPython boards via pyserial raw REPL.

    All source code is sent inline through the raw REPL — no file copy
    or mounting needed.

    Args:
        address: Serial port path (e.g. ``/dev/cu.usbmodem14101``).
        baudrate: Serial baud rate.  Defaults to 115200.
        timeout: Read timeout in seconds.
        serial_port_factory: Callable that creates a serial port object.
            Accepts ``(port, baudrate, timeout)`` keyword arguments.
            Defaults to ``serial.Serial``.  Inject a fake for testing.
        sleep: Callable for delays between serial operations.
            Defaults to ``time.sleep``.  Inject a no-op for testing.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        timeout: float = DEFAULT_TIMEOUT,
        serial_port_factory: Callable[..., object] | None = None,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial_port_factory = serial_port_factory
        self._sleep = sleep or time.sleep
        self._port: object | None = None
        self._staged_sources: list[tuple[str, str]] | None = None

    def _get_serial_port_factory(self):
        """Return the serial port factory, importing pyserial lazily."""
        if self._serial_port_factory is not None:
            return self._serial_port_factory
        import serial  # pragma: no cover
        return serial.Serial  # pragma: no cover

    def connect(self) -> None:
        """Open the serial port and enter raw REPL mode.

        Sends Ctrl-C × 2 to interrupt any running code, then Ctrl-A
        to enter raw REPL.

        Raises:
            CircuitpythonTransportError: If the serial port cannot be
                opened or raw REPL prompt is not received.
        """
        factory = self._get_serial_port_factory()
        try:
            self._port = factory(
                port=self.address,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
        except Exception as open_error:
            raise CircuitpythonTransportError(
                f"Failed to open serial port {self.address}: {open_error}"
            ) from open_error

        self._enter_raw_repl()

    def _enter_raw_repl(self) -> None:
        """Interrupt running code and switch to raw REPL mode."""
        # Ctrl-C × 2 to interrupt any running program.
        self._port.write(_CTRL_C)
        self._sleep(_INTERRUPT_DELAY)
        self._port.write(_CTRL_C)
        self._sleep(_INTERRUPT_DELAY)

        # Drain any pending output before entering raw REPL.
        self._port.reset_input_buffer()

        # Ctrl-A to enter raw REPL.
        self._port.write(_CTRL_A)
        self._sleep(_ENTER_DELAY)

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

        CircuitPython transport does not copy files to the device.
        Instead, all source code is read now and embedded into the
        bootstrap code block sent via raw REPL during ``execute()``.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage (stored for bootstrap
                generation).
            harness_source: Path to the test harness ``src/`` directory.
        """
        self._staged_sources = []
        # Collect library package sources.
        for source_directory in source_dirs:
            self._collect_package_sources(source_directory)
        # Collect harness sources.
        self._collect_package_sources(harness_source)

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
            self._sleep(0.5)

    def disconnect(self) -> None:
        """Close the serial port and clear staged data."""
        if self._port is not None:
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
        accumulated = b""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            waiting = self._port.in_waiting
            if waiting > 0:
                chunk = self._port.read(waiting)
                accumulated += chunk
                if marker in accumulated:
                    return accumulated
            else:
                self._sleep(0.01)
        return accumulated

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

