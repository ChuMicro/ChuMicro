"""MicroPython device transport using mpremote.

Uses the ``mpremote`` CLI tool (subprocess) to connect to MicroPython
boards, stage files, and execute test scripts.  Two modes:

- **Mount mode** (default): ``mpremote mount`` streams files from the
  host — no flash wear, fast iteration.
- **Copy mode** (fallback): ``mpremote fs cp -r`` writes files to flash,
  then runs the bootstrap script.

See Decision 0027 for the full transport protocol.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path


class MicropythonTransportError(Exception):
    """Raised when an mpremote command fails."""


class MicropythonTransport:
    """Transport for MicroPython boards via mpremote.

    Args:
        address: Serial port or network address of the device.
        mode: ``"mount"`` (default) or ``"copy"``.
        runner: Callable that executes subprocess commands.  Accepts
            the same signature as ``subprocess.run``.  Defaults to
            ``subprocess.run``.  Inject a fake for testing.
    """

    def __init__(
        self,
        address: str,
        *,
        mode: str = "mount",
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.address = address
        self.mode = mode
        self._runner = runner or subprocess.run
        self._staging_dir: tempfile.TemporaryDirectory | None = None
        self._staging_path: Path | None = None

    def connect(self) -> None:
        """Verify the device is reachable by running a no-op command."""
        self._run_mpremote(["exec", "print('ok')"])

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
    ) -> None:
        """Prepare a staging directory with library sources, tests, and harness.

        In mount mode, the staging directory is mounted on the device.
        In copy mode, it is recursively copied to flash.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage.
            harness_source: Path to the test harness ``src/`` directory.
        """
        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_device_")
        self._staging_path = Path(self._staging_dir.name)

        # Copy source packages into staging.
        for source_dir in source_dirs:
            self._copy_tree(source_dir, self._staging_path)

        # Copy harness source.
        self._copy_tree(harness_source, self._staging_path)

        # Copy test files into staging root.
        for test_file in test_files:
            destination = self._staging_path / test_file.name
            destination.write_bytes(test_file.read_bytes())

        if self.mode == "copy":
            self._run_mpremote([
                "fs", "cp", "-r",
                str(self._staging_path) + "/.",
                ":",
            ])

    def execute(self, bootstrap_script: str) -> str:
        """Execute a bootstrap script on the device and return captured output.

        In mount mode, the staging directory is mounted and the bootstrap
        script is run directly.  In copy mode, files are already on flash
        so the script is executed via ``exec``.

        Args:
            bootstrap_script: Python code to execute on the device.

        Returns:
            Captured stdout from the device.
        """
        if self._staging_path is None:
            raise MicropythonTransportError(
                "stage() must be called before execute()"
            )

        # Write bootstrap to a temp file.
        bootstrap_file = self._staging_path / "_bootstrap.py"
        bootstrap_file.write_text(bootstrap_script)

        if self.mode == "mount":
            result = self._run_mpremote([
                "mount", str(self._staging_path),
                "run", str(bootstrap_file),
            ])
        else:
            result = self._run_mpremote(["run", str(bootstrap_file)])

        return result.stdout

    def reset(self) -> None:
        """Soft-reset the device."""
        self._run_mpremote(["reset"])

    def disconnect(self) -> None:
        """Clean up staging directory."""
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

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

