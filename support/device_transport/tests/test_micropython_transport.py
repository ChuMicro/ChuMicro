"""Tests for MicropythonTransport — mpremote-based device transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from chumicro_device_transport.micropython_transport import (
    MicropythonTransport,
    MicropythonTransportError,
)
from chumicro_device_transport.testing import FakeTransport


@dataclass
class FakeSubprocessResult:
    """Mimics subprocess.CompletedProcess for testing."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeRunner:
    """Records subprocess.run calls and returns canned results."""

    def __init__(self, results: list[FakeSubprocessResult] | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._results = list(results) if results else []
        self._default = FakeSubprocessResult()

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self._results:
            return self._results.pop(0)
        return self._default


class TestConnect:
    """Tests for MicropythonTransport.connect."""

    def test_connect_runs_exec_print(self) -> None:
        """connect() should run mpremote exec print('ok')."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.connect()

        assert len(runner.calls) == 1
        command = runner.calls[0][0]
        assert command == ["mpremote", "connect", "/dev/ttyUSB0", "exec", "print('ok')"]

    def test_connect_failure_raises(self) -> None:
        """connect() should raise when mpremote fails."""
        runner = FakeRunner([FakeSubprocessResult(returncode=1, stderr="no device")])
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)

        with pytest.raises(MicropythonTransportError, match="mpremote command failed"):
            transport.connect()


class TestStage:
    """Tests for MicropythonTransport.stage."""

    def test_mount_mode_does_not_copy_to_device(self, tmp_path) -> None:
        """In mount mode, stage() should prepare a local directory without running fs cp."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "ticks.py").write_text("# ticks")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()
        harness_package = harness_dir / "chumicro_test_harness"
        harness_package.mkdir()
        (harness_package / "__init__.py").write_text("# harness")

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", mode="mount", runner=runner)
        transport.stage([source_dir], [test_file], harness_dir)

        # Mount mode: no mpremote fs cp calls during stage.
        assert len(runner.calls) == 0

        # Staging directory should exist with copies.
        assert transport._staging_path is not None
        assert (transport._staging_path / "chumicro_timing" / "ticks.py").exists()
        assert (transport._staging_path / "test_example.py").exists()
        assert (transport._staging_path / "chumicro_test_harness" / "__init__.py").exists()

        transport.disconnect()

    def test_copy_mode_runs_fs_cp(self, tmp_path) -> None:
        """In copy mode, stage() should run mpremote fs cp -r."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("# module")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", mode="copy", runner=runner)
        transport.stage([source_dir], [], harness_dir)

        assert len(runner.calls) == 1
        command = runner.calls[0][0]
        assert "fs" in command
        assert "cp" in command
        assert "-r" in command

        transport.disconnect()


class TestExecute:
    """Tests for MicropythonTransport.execute."""

    def test_mount_mode_uses_mount_and_run(self, tmp_path) -> None:
        """In mount mode, execute() should use mpremote mount + run."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner([FakeSubprocessResult(stdout="PASS test_ok (0.001s)\n")])
        transport = MicropythonTransport("/dev/ttyUSB0", mode="mount", runner=runner)
        transport.stage([source_dir], [], harness_dir)
        runner.calls.clear()

        output = transport.execute("import test_example")

        assert len(runner.calls) == 1
        command = runner.calls[0][0]
        assert "mount" in command
        assert "run" in command
        assert output == "PASS test_ok (0.001s)\n"

        transport.disconnect()

    def test_copy_mode_uses_run_only(self, tmp_path) -> None:
        """In copy mode, execute() should use mpremote run without mount."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # stage() produces one call in copy mode (fs cp), then execute() produces another.
        runner = FakeRunner([
            FakeSubprocessResult(),  # stage fs cp
            FakeSubprocessResult(stdout="PASS test_ok (0.001s)\n"),  # execute run
        ])
        transport = MicropythonTransport("/dev/ttyUSB0", mode="copy", runner=runner)
        transport.stage([source_dir], [], harness_dir)
        output = transport.execute("import test_example")

        execute_command = runner.calls[1][0]
        assert "mount" not in execute_command
        assert "run" in execute_command
        assert output == "PASS test_ok (0.001s)\n"

        transport.disconnect()

    def test_execute_before_stage_raises(self) -> None:
        """execute() without prior stage() should raise."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)

        with pytest.raises(MicropythonTransportError, match="stage"):
            transport.execute("print('hello')")

    def test_execute_failure_raises(self, tmp_path) -> None:
        """execute() should raise when the mpremote command fails."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner([
            FakeSubprocessResult(returncode=1, stderr="device error"),
        ])
        transport = MicropythonTransport("/dev/ttyUSB0", mode="mount", runner=runner)
        transport.stage([source_dir], [], harness_dir)

        with pytest.raises(MicropythonTransportError):
            transport.execute("import test_example")

        transport.disconnect()


class TestReset:
    """Tests for MicropythonTransport.reset."""

    def test_reset_runs_mpremote_reset(self) -> None:
        """reset() should run mpremote reset."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.reset()

        command = runner.calls[0][0]
        assert command == ["mpremote", "connect", "/dev/ttyUSB0", "reset"]


class TestDisconnect:
    """Tests for MicropythonTransport.disconnect."""

    def test_disconnect_cleans_up_staging(self, tmp_path) -> None:
        """disconnect() should clean up the staging directory."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.stage([source_dir], [], harness_dir)

        staging_path = transport._staging_path
        assert staging_path.exists()

        transport.disconnect()
        assert transport._staging_path is None
        assert not staging_path.exists()

    def test_disconnect_without_stage_is_safe(self) -> None:
        """disconnect() should not raise when stage() was never called."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.disconnect()  # Should not raise.


class TestFakeTransport:
    """Tests for the FakeTransport test double."""

    def test_records_calls(self) -> None:
        """FakeTransport should record the sequence of calls."""
        fake = FakeTransport(execute_output="PASS test_ok (0.001s)\n")
        fake.connect()
        fake.stage([], [], None)
        output = fake.execute("script")
        fake.reset()
        fake.disconnect()

        assert output == "PASS test_ok (0.001s)\n"
        assert len(fake.calls) == 5
        assert fake.calls[0] == ("connect", ())
        assert fake.calls[1][0] == "stage"
        assert fake.calls[2][0] == "execute"
        assert fake.calls[3] == ("reset", ())
        assert fake.calls[4] == ("disconnect", ())

    def test_connected_state(self) -> None:
        """FakeTransport should track connected state."""
        fake = FakeTransport()
        assert not fake.connected
        fake.connect()
        assert fake.connected
        fake.disconnect()
        assert not fake.connected

