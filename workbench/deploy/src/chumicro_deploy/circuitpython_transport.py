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
import tempfile
import time as _time_module
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from . import flash_drive
from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    parse_probe_output,
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

#: Volume name CircuitPython uses by default.
_CIRCUITPY_VOLUME_NAME = "CIRCUITPY"

# RAM-mode inline scripts are chunked based on live free-heap measurements.
_MIN_INLINE_SCRIPT_BUDGET_BYTES = 8 * 1024
_MAX_INLINE_SCRIPT_BUDGET_BYTES = 48 * 1024


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


class TimeSource(Protocol):
    """Structural interface for an injectable time source.

    Matches the subset of Python's ``time`` module used by the transport.
    ``FakeTime`` from ``chumicro_abstractions`` satisfies this protocol
    so tests can eliminate wall-clock waits.
    """

    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


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
        # Set true by reset_into_bootloader() so the next disconnect()
        # skips its "restore board state" dance — the board is gone
        # from USB and any raw-REPL traffic at that point is noise.
        self._reset_pending = False

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

    def _resolve_circuitpy_drive(self) -> Path:
        """Return the CIRCUITPY drive path, raising if it isn't usable.

        Uses the configured ``circuitpy_drive_path`` when set, otherwise
        falls back to :func:`find_circuitpy_drive`.  Raises when no drive
        can be found or the resolved path is not a directory (e.g. the
        board ejected mid-run).
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
        return drive_path

    @staticmethod
    def _build_local_staging_tree(
        staging_path: Path,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
    ) -> None:
        """Mirror the desired drive layout inside a local staging directory.

        Library and harness packages go under ``lib/``; test files go at
        the root.  Building locally is reliable (no FAT32 quirks) — only
        the rsync that follows has to deal with the device drive.
        macOS extended attributes are stripped at the end so ``._``
        resource forks don't end up on the FAT32 volume.
        """
        lib_staging = staging_path / "lib"
        lib_staging.mkdir()
        for source_directory in source_dirs:
            flash_drive.merge_packages(source_directory, lib_staging)
        flash_drive.merge_packages(harness_source, lib_staging)

        for test_file in test_files:
            shutil.copy2(test_file, staging_path / test_file.name)

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

        # Prevent macOS Spotlight from indexing the drive — it creates
        # hidden metadata files and slows down FAT32 writes.
        flash_drive.disable_spotlight_indexing(drive_path)

        # Disable autoreload to prevent restarts during file copy.
        self._send_repl_command(
            "import supervisor; "
            "supervisor.runtime.autoreload = False"
        )

        with tempfile.TemporaryDirectory() as staging_directory:
            staging_path = Path(staging_directory)
            self._build_local_staging_tree(
                staging_path, source_dirs, test_files, harness_source,
            )
            try:
                flash_drive.rsync(staging_path, drive_path)
            except flash_drive.FlashDriveError as error:
                raise CircuitpythonTransportError(str(error)) from error

        # Remove ._ resource fork files that macOS may have created
        # on the FAT32 volume despite rsync's --exclude=._* flag.
        flash_drive.clean_dot_files(drive_path)

        # Flush the volume so the device reads current content.
        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

        self._warn_if_flush_produced_empty_file(drive_path, test_files)

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

        Sets :attr:`_reset_pending` so a subsequent :meth:`disconnect`
        does not try to restore board state on a USB link that just
        went away — that dance would produce misleading warnings
        when the user specifically asked for a bootloader reset.
        """
        if self._port is None:
            return False
        self._reset_pending = True
        try:
            self._send_repl_command(
                "import microcontroller\n"
                "microcontroller.on_next_reset("
                "microcontroller.RunMode.BOOTLOADER)\n"
                "microcontroller.reset()\n"
            )
        except Exception:
            pass
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

    def reset(self) -> None:
        """Soft-reset the device via Ctrl-D."""
        if self._port is not None:
            self._port.write(_CTRL_D)
            # Allow time for the reset to complete.
            self._time.sleep(0.5)

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
        """Write *files* to the CIRCUITPY drive and execute *entrypoint*.

        Flash mode only.  Writes every entry of *files* to the CIRCUITPY
        USB drive (auto-detecting the mount path when not configured),
        flushes the volume, then execs the entrypoint through the
        persistent raw REPL.  Autoreload is disabled during writes so
        the board does not reset mid-deploy.

        RAM-mode deploy is deliberately not implemented — it would
        require a generalised module-injection path (the existing
        test-harness-specific ``build_circuitpython_bootstrap`` is
        tightly coupled to dotted-module-name sources and the test
        runner).  Use ``deploy_mode="flash"`` for deploy-then-exec;
        stick with ``stage()`` + ``execute_scripts()`` for the test-
        harness RAM-mode flow.

        Args:
            files: On-device-path -> bytes mapping.  The leading slash
                is stripped before joining with the drive mount point.
            entrypoint: On-device path (must be a key of *files*).
            on_file_staged: Per-file callback invoked after each file
                is written to the drive.
            on_execute_line: Callback invoked once per line of captured
                output (in order) after the entrypoint returns.

        Returns:
            Combined stdout from the entrypoint execution.

        Raises:
            CircuitpythonTransportError: If RAM mode is selected, the
                port is not connected, the CIRCUITPY drive cannot be
                located, or the entrypoint is not in *files*.
        """
        if self.mode == "ram":
            raise CircuitpythonTransportError(
                "CircuitpythonTransport.deploy_files does not support "
                "deploy_mode='ram' — use deploy_mode='flash' for "
                "deploy-then-exec, or the test-harness stage/execute "
                "flow for RAM-mode test runs."
            )
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before deploy_files()"
            )
        if entrypoint not in files:
            raise CircuitpythonTransportError(
                f"entrypoint {entrypoint!r} missing from files "
                f"({sorted(files.keys())!r})"
            )

        drive_path_string = self.circuitpy_drive_path or find_circuitpy_drive()
        if drive_path_string is None:
            raise CircuitpythonTransportError(
                "CIRCUITPY drive not found — pass circuitpy_drive_path "
                "explicitly or mount the drive before calling deploy_files()."
            )
        drive_path = Path(drive_path_string)

        self._enter_raw_repl()
        self._send_repl_command(
            "import supervisor; supervisor.runtime.autoreload = False"
        )

        for device_path in sorted(files.keys()):
            relative = device_path.lstrip("/")
            destination = drive_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(files[device_path])
            if on_file_staged is not None:
                on_file_staged(device_path)

        flash_drive.flush_volume(drive_path, sleep=self._time.sleep)

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

    def _read_code_py_output(self) -> str:
        """Read serial output from a fresh boot until code.py completes.

        CircuitPython prints ``Code done running.`` when code.py
        returns (or raises).  For infinite-loop entrypoints the
        marker never appears and the read times out at
        :attr:`timeout` seconds — callers receive the accumulated
        output up to that point.

        Returns:
            The portion of captured serial output between the
            ``soft reboot`` marker and the ``Code done running.``
            marker (if present), or everything after ``soft reboot``
            if the marker is absent.
        """
        assert self._port is not None
        done_marker = b"Code done running."
        accumulated = b""
        deadline = self._time.monotonic() + self.timeout
        while self._time.monotonic() < deadline:
            waiting = self._port.in_waiting
            if waiting > 0:
                accumulated += self._port.read(waiting)
                if done_marker in accumulated:
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
        2. In flash mode, re-enables autoreload via supervisor.
        3. Exits raw REPL with Ctrl-B (back to normal REPL).
        4. Soft-reboots with Ctrl-D so code.py runs normally.
        5. Waits briefly for the reboot to complete.
        6. Closes the serial port.

        When :attr:`_reset_pending` is set (e.g. after
        :meth:`reset_into_bootloader`), steps 1–5 are skipped —
        the board is already mid-reset and there's nothing sensible
        to talk to.  The port is closed silently; no warnings are
        printed for a link that went away on purpose.
        """
        if self._port is not None:
            if not self._reset_pending:
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
                if not self._reset_pending:
                    print(f"WARNING: Failed to close serial port on disconnect: {close_error}")
            self._port = None
        self._staged_sources = None
        self._reset_pending = False

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
