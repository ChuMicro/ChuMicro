"""Tests for MicropythonTransport — persistent serial + subprocess fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class FakeSerialTransport:
    """In-memory stand-in for ``mpremote.transport_serial.SerialTransport``.

    Records every method call so tests can assert on the persistent
    serial path without touching real hardware.
    """

    address: str
    baudrate: int = 115200
    exec_outputs: list[bytes] = field(default_factory=list)
    raise_on_execute: Exception | None = None
    calls: list[tuple[str, tuple]] = field(default_factory=list)

    def enter_raw_repl(self, soft_reset: bool = True) -> None:
        self.calls.append(("enter_raw_repl", (soft_reset,)))

    def exit_raw_repl(self) -> None:
        self.calls.append(("exit_raw_repl", ()))

    def mount_local(self, path: str, unsafe_links: bool = False) -> None:
        self.calls.append(("mount_local", (path,)))

    def umount_local(self) -> None:
        self.calls.append(("umount_local", ()))

    def exec_raw(self, command: str, timeout: int = 10) -> bytes:
        self.calls.append(("exec_raw", (command, timeout)))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        if self.exec_outputs:
            return self.exec_outputs.pop(0)
        return b""

    def close(self) -> None:
        self.calls.append(("close", ()))


def _factory_for(serial: FakeSerialTransport):
    """Build a transport_factory that returns *serial* and records args."""

    def factory(address: str, baudrate: int) -> FakeSerialTransport:
        serial.calls.append(("__factory__", (address, baudrate)))
        return serial

    return factory


class TestConnect:
    """Tests for MicropythonTransport.connect."""

    def test_connect_runs_exec_print(self) -> None:
        """connect() should run mpremote exec print('ok') (subprocess no-op verify)."""
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

    def test_mount_mode_opens_serial_and_mounts_staging(self, tmp_path) -> None:
        """In mount mode, stage() opens the serial transport and mounts the staging dir."""
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
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [test_file], harness_dir)

        # Mount mode never invokes mpremote subprocess during stage.
        assert len(runner.calls) == 0

        # Staging directory should exist with copies.
        assert transport._staging_path is not None
        assert (transport._staging_path / "chumicro_timing" / "ticks.py").exists()
        assert (transport._staging_path / "test_example.py").exists()
        assert (transport._staging_path / "chumicro_test_harness" / "__init__.py").exists()

        # Serial transport opened, raw REPL entered, staging mounted.
        method_names = [name for name, _ in serial.calls]
        assert "__factory__" in method_names
        assert "enter_raw_repl" in method_names
        assert "mount_local" in method_names

        transport.disconnect()

    def test_copy_mode_runs_fs_cp_and_does_not_open_serial(self, tmp_path) -> None:
        """In copy mode, stage() runs mpremote fs cp -r and leaves serial closed."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("# module")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="copy",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        # One mpremote subprocess call: the fs cp -r.
        assert len(runner.calls) == 1
        command = runner.calls[0][0]
        assert "fs" in command
        assert "cp" in command
        assert "-r" in command

        # Serial transport stays closed during copy-mode stage.
        assert serial.calls == []

        transport.disconnect()


class TestExecute:
    """Tests for MicropythonTransport.execute."""

    def test_mount_mode_uses_persistent_exec_raw(self, tmp_path) -> None:
        """In mount mode, execute() runs exec_raw on the persistent serial transport.

        The whole point of the persistent path: no per-execute mpremote
        subprocess.  Confirms commit-3's perf fix is wired up.
        """
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[b"PASS test_ok (0.001s)\n"],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        # No subprocess calls during stage in mount mode; clear runner anyway.
        runner.calls.clear()

        output = transport.execute("import test_example")

        # Critical: NO subprocess invocation per execute().
        assert runner.calls == []

        # Serial transport got an exec_raw call with the bootstrap content.
        exec_calls = [args for name, args in serial.calls if name == "exec_raw"]
        assert len(exec_calls) == 1
        assert exec_calls[0][0] == "import test_example"

        # Output decoded and returned.
        assert output == "PASS test_ok (0.001s)\n"

        transport.disconnect()

    def test_copy_mode_opens_serial_lazily_and_uses_exec_raw(self, tmp_path) -> None:
        """In copy mode, execute() lazily opens the serial transport (released by stage)."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner([
            FakeSubprocessResult(),  # stage's fs cp
        ])
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[b"PASS test_ok (0.001s)\n"],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="copy",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)
        # Serial closed after stage's fs cp.
        assert serial.calls == []

        output = transport.execute("import test_example")

        # Serial opened lazily on first execute().
        method_names = [name for name, _ in serial.calls]
        assert "__factory__" in method_names
        assert "enter_raw_repl" in method_names
        assert "exec_raw" in method_names
        # No mount_local in copy mode (files are on flash).
        assert "mount_local" not in method_names

        assert output == "PASS test_ok (0.001s)\n"

        transport.disconnect()

    def test_execute_before_stage_raises(self) -> None:
        """execute() without prior stage() should raise."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)

        with pytest.raises(MicropythonTransportError, match="stage"):
            transport.execute("print('hello')")

    def test_execute_failure_raises(self, tmp_path) -> None:
        """execute() should wrap the underlying SerialTransport error."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            raise_on_execute=RuntimeError("device disconnected"),
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        with pytest.raises(MicropythonTransportError, match="device disconnected"):
            transport.execute("import test_example")

        transport.disconnect()


class TestReset:
    """Tests for MicropythonTransport.reset / soft_reset."""

    def test_reset_without_serial_runs_subprocess(self) -> None:
        """reset() without an open serial transport runs mpremote reset."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.reset()

        command = runner.calls[0][0]
        assert command == ["mpremote", "connect", "/dev/ttyUSB0", "reset"]

    def test_reset_with_serial_re_enters_raw_repl(self, tmp_path) -> None:
        """reset() with an open serial transport re-enters raw REPL with soft_reset=True."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        # Reset path: exit_raw_repl, then enter_raw_repl(soft_reset=True),
        # then mount_local again to restore the staged mount.
        prior_call_count = len(serial.calls)
        transport.reset()
        new_calls = [name for name, _ in serial.calls[prior_call_count:]]
        assert "exit_raw_repl" in new_calls
        assert "enter_raw_repl" in new_calls
        assert "mount_local" in new_calls
        # No mpremote subprocess call.
        assert runner.calls == []

        transport.disconnect()


class TestRecover:
    """Tests for MicropythonTransport.recover."""

    def test_recover_closes_serial_then_runs_mpremote_reset(self, tmp_path) -> None:
        """recover() closes the persistent transport then issues a subprocess reset."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        transport.recover()

        # Serial closed.
        assert "close" in [name for name, _ in serial.calls]
        assert transport._serial is None
        # Subprocess reset issued.
        assert any(call[0][-1] == "reset" for call in runner.calls)

        transport.disconnect()


class TestDisconnect:
    """Tests for MicropythonTransport.disconnect."""

    def test_disconnect_cleans_up_staging(self, tmp_path) -> None:
        """disconnect() should clean up the staging directory and close serial."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        staging_path = transport._staging_path
        assert staging_path.exists()

        transport.disconnect()
        assert transport._staging_path is None
        assert not staging_path.exists()
        assert transport._serial is None
        # Disconnect path called umount_local + exit_raw_repl + close.
        method_names = [name for name, _ in serial.calls]
        assert "umount_local" in method_names
        assert "exit_raw_repl" in method_names
        assert "close" in method_names

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
        fake.soft_reset()
        fake.reset()
        fake.disconnect()

        assert output == "PASS test_ok (0.001s)\n"
        assert len(fake.calls) == 6
        assert fake.calls[0] == ("connect", ())
        assert fake.calls[1][0] == "stage"
        assert fake.calls[2][0] == "execute"
        assert fake.calls[3] == ("soft_reset", ())
        assert fake.calls[4] == ("reset", ())
        assert fake.calls[5] == ("disconnect", ())

    def test_connected_state(self) -> None:
        """FakeTransport should track connected state."""
        fake = FakeTransport()
        assert not fake.connected
        fake.connect()
        assert fake.connected
        fake.disconnect()
        assert not fake.connected
