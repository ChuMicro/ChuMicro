"""Tests for MicropythonTransport — persistent serial + subprocess fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from chumicro_deploy.micropython_transport import (
    MicropythonTransport,
    MicropythonTransportError,
)
from chumicro_deploy.testing import FakeTransport


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
    # Real mpremote returns ``(stdout_bytes, stderr_bytes)`` from ``exec_raw``.
    # Tests may pass either a tuple or a bare bytes value for convenience;
    # bare bytes are wrapped into ``(bytes, b"")`` to mirror hardware.
    exec_outputs: list[tuple[bytes, bytes] | bytes] = field(default_factory=list)
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

    def exec_raw(self, command: str, timeout: int = 10) -> tuple[bytes, bytes]:
        self.calls.append(("exec_raw", (command, timeout)))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        if self.exec_outputs:
            value = self.exec_outputs.pop(0)
            if isinstance(value, tuple):
                return value
            return (value, b"")
        return (b"", b"")

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
        # command[0] is a resolved path (e.g. .venv/bin/mpremote) — just
        # confirm it points at an mpremote binary, then check the rest.
        assert command[0].endswith("mpremote") or command[0].endswith("mpremote.exe")
        assert command[1:] == ["connect", "/dev/ttyUSB0", "exec", "print('ok')"]

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

    def test_re_stage_unmounts_before_remounting(self, tmp_path) -> None:
        """Re-staging on a live transport must umount before the next mount_local.

        Regression: pytest_device's RAM-mode orchestration calls
        ``stage()`` once per test file on the *same* transport.  Without
        this, mpremote's on-device mount hook raises
        ``OSError: [Errno 1] EPERM`` on the second ``mount_local``
        because the first mount is still live — breaking every
        multi-file IDE session on MicroPython.
        """
        source_a = tmp_path / "src_a"
        source_a.mkdir()
        source_b = tmp_path / "src_b"
        source_b.mkdir()
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

        transport.stage([source_a], [], harness_dir)
        first_staging_path = transport._staging_path
        transport.stage([source_b], [], harness_dir)
        second_staging_path = transport._staging_path

        # A fresh tempdir was created and the old one cleaned up.
        assert first_staging_path != second_staging_path
        assert not first_staging_path.exists()
        assert second_staging_path.exists()

        # Lifecycle: mount → umount → mount, with the second mount
        # targeting the new staging path.
        lifecycle = [name for name, _ in serial.calls]
        first_mount_index = lifecycle.index("mount_local")
        umount_index = lifecycle.index("umount_local", first_mount_index)
        second_mount_index = lifecycle.index("mount_local", umount_index)
        assert first_mount_index < umount_index < second_mount_index

        mount_targets = [
            args[0] for name, args in serial.calls if name == "mount_local"
        ]
        assert mount_targets[0] == str(first_staging_path)
        assert mount_targets[1] == str(second_staging_path)

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

    def test_execute_merges_stdout_and_stderr(self, tmp_path) -> None:
        """execute() unpacks mpremote's ``(stdout, stderr)`` tuple and merges both.

        Regression: mpremote's :meth:`SerialTransport.exec_raw` returns a
        ``(stdout_bytes, stderr_bytes)`` tuple, not a single ``bytes``.
        A prior implementation returned the tuple unchanged, which later
        caused ``'tuple' object has no attribute 'splitlines'`` when the
        result parser tried to process the captured output.  Stderr must
        be merged in so a device-side traceback shows up in the log.
        """
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[(b"PASS test_ok (0.001s)\n", b"Traceback boom\n")],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        output = transport.execute("import test_example")

        assert isinstance(output, str)
        assert "PASS test_ok (0.001s)" in output
        assert "Traceback boom" in output

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


class TestSoftReset:
    """Tests for MicropythonTransport.soft_reset."""

    def test_soft_reset_without_serial_runs_subprocess(self) -> None:
        """soft_reset() without an open serial transport runs mpremote reset."""
        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport.soft_reset()

        command = runner.calls[0][0]
        assert command[0].endswith("mpremote") or command[0].endswith("mpremote.exe")
        assert command[1:] == ["connect", "/dev/ttyUSB0", "reset"]

    def test_soft_reset_with_serial_umounts_then_re_enters_raw_repl(self, tmp_path) -> None:
        """soft_reset() with an open serial transport umounts, exits, then soft-resets.

        The mount is deliberately *not* restored inside ``soft_reset``;
        ``stage()`` owns remounting.  Re-mounting here would double-wrap
        ``mpremote``'s ``SerialIntercept`` and break I/O on the next
        file.  This test locks in that contract.
        """
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

        prior_call_count = len(serial.calls)
        transport.soft_reset()
        new_calls = [name for name, _ in serial.calls[prior_call_count:]]
        # Contract: umount_local must come before enter_raw_repl so the
        # SerialIntercept is unwrapped while device-side mount state is
        # still live.
        assert "umount_local" in new_calls
        assert "exit_raw_repl" in new_calls
        assert "enter_raw_repl" in new_calls
        assert new_calls.index("umount_local") < new_calls.index("enter_raw_repl")
        # soft_reset must NOT re-mount — that belongs to stage().
        assert "mount_local" not in new_calls
        # _mounted flag cleared so the next stage() won't try to umount
        # twice.
        assert transport._mounted is False
        # No mpremote subprocess call.
        assert runner.calls == []

        transport.disconnect()

    def test_soft_reset_followed_by_stage_mounts_new_path_cleanly(
        self, tmp_path,
    ) -> None:
        """End-to-end: soft_reset then stage() must unwrap, reset, and remount.

        Regression: after soft_reset the device globals are gone, so
        attempting to umount the old mount later would fail because
        ``os.umount`` has nothing to call.  stage() must not try to
        umount again (soft_reset already did), but must still create a
        fresh tempdir and mount it.
        """
        source_a = tmp_path / "src_a"
        source_a.mkdir()
        source_b = tmp_path / "src_b"
        source_b.mkdir()
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
        transport.stage([source_a], [], harness_dir)
        transport.soft_reset()
        transport.stage([source_b], [], harness_dir)

        # Two mount_local calls total — one per stage() — never from
        # soft_reset.  Each must be immediately preceded by either the
        # initial raw REPL entry or a soft-reset enter_raw_repl.
        mount_calls = [
            index for index, (name, _) in enumerate(serial.calls)
            if name == "mount_local"
        ]
        umount_calls = [
            index for index, (name, _) in enumerate(serial.calls)
            if name == "umount_local"
        ]
        assert len(mount_calls) == 2
        # Exactly one umount: inside soft_reset (stage() skipped its
        # own umount because soft_reset already cleared _mounted).
        assert len(umount_calls) == 1
        assert umount_calls[0] < mount_calls[1]

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
        fake.disconnect()

        assert output == "PASS test_ok (0.001s)\n"
        assert len(fake.calls) == 5
        assert fake.calls[0] == ("connect", ())
        assert fake.calls[1][0] == "stage"
        assert fake.calls[2][0] == "execute"
        assert fake.calls[3] == ("soft_reset", ())
        assert fake.calls[4] == ("disconnect", ())

    def test_connected_state(self) -> None:
        """FakeTransport should track connected state."""
        fake = FakeTransport()
        assert not fake.connected
        fake.connect()
        assert fake.connected
        fake.disconnect()
        assert not fake.connected


class TestProbeImplementation:
    """Tests for MicropythonTransport.probe_implementation."""

    def test_parses_probe_marker_from_exec_raw_tuple(self) -> None:
        """mpremote's (stdout, stderr) tuple is decoded and parsed for the marker."""
        from chumicro_deploy import DeviceImplementation

        runner = FakeRunner()
        probe_stdout = (
            b"__CHU_IMPL__:micropython|1.26.0|Raspberry Pi Pico W with RP2040\n"
        )
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[(probe_stdout, b"")],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )

        result = transport.probe_implementation()

        assert result == DeviceImplementation(
            name="micropython",
            version="1.26.0",
            machine="Raspberry Pi Pico W with RP2040",
        )
        # Probe opens the persistent serial lazily but does NOT require
        # stage() — the probe script only touches sys.implementation.
        exec_calls = [args for name, args in serial.calls if name == "exec_raw"]
        assert len(exec_calls) == 1

    def test_probe_failure_returns_none(self) -> None:
        """A raising exec_raw yields None so the test run still proceeds."""
        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            raise_on_execute=RuntimeError("serial dropped"),
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )

        assert transport.probe_implementation() is None

    def test_probe_missing_marker_returns_none(self) -> None:
        """Output without the marker returns None, does not raise."""
        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[(b"no marker here\n", b"")],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )

        assert transport.probe_implementation() is None


class TestResolveMpremoteBinary:
    """The subprocess fallback must locate mpremote without a pre-activated .venv."""

    def test_prefers_venv_bin_sibling_of_sys_executable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """When mpremote sits next to sys.executable, subprocess uses that path."""
        from chumicro_deploy import micropython_transport as module

        venv_bin = tmp_path / "bin"
        venv_bin.mkdir()
        fake_python = venv_bin / "python"
        fake_python.touch()
        fake_mpremote = venv_bin / "mpremote"
        fake_mpremote.write_text("#!/usr/bin/env python\n")
        fake_mpremote.chmod(0o755)

        monkeypatch.setattr(module.sys, "executable", str(fake_python))

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport._run_mpremote(["reset"])

        command, _ = runner.calls[-1]
        assert command[0] == str(fake_mpremote), (
            f"expected venv-local mpremote, got {command[0]!r}"
        )

    def test_falls_back_to_path_lookup_when_venv_bin_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Without a venv-local binary, shutil.which on PATH is used."""
        from chumicro_deploy import micropython_transport as module

        empty_bin = tmp_path / "bin"
        empty_bin.mkdir()
        fake_python = empty_bin / "python"
        fake_python.touch()

        monkeypatch.setattr(module.sys, "executable", str(fake_python))
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/opt/homebrew/bin/mpremote" if name == "mpremote" else None,
        )

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport._run_mpremote(["reset"])

        command, _ = runner.calls[-1]
        assert command[0] == "/opt/homebrew/bin/mpremote"

    def test_final_fallback_keeps_bare_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Neither venv-local nor PATH hit → command stays as bare ``mpremote``."""
        from chumicro_deploy import micropython_transport as module

        empty_bin = tmp_path / "bin"
        empty_bin.mkdir()
        fake_python = empty_bin / "python"
        fake_python.touch()

        monkeypatch.setattr(module.sys, "executable", str(fake_python))
        monkeypatch.setattr("shutil.which", lambda name: None)

        runner = FakeRunner()
        transport = MicropythonTransport("/dev/ttyUSB0", runner=runner)
        transport._run_mpremote(["reset"])

        command, _ = runner.calls[-1]
        assert command[0] == "mpremote"


class TestResetIntoBootloader:
    """Tests for MicropythonTransport.reset_into_bootloader."""

    def test_dispatches_machine_bootloader_and_returns_true(self) -> None:
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            transport_factory=_factory_for(serial),
            runner=FakeRunner(),
        )
        assert transport.reset_into_bootloader() is True
        exec_call = next(
            (call for call in serial.calls if call[0] == "exec_raw"), None,
        )
        assert exec_call is not None
        assert "machine.bootloader" in exec_call[1][0]

    def test_exec_raw_failure_swallowed_returns_true(self) -> None:
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        serial.raise_on_execute = RuntimeError("reset drops serial link")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            transport_factory=_factory_for(serial),
            runner=FakeRunner(),
        )
        # exec_raw raising is the EXPECTED success signal — the board
        # resets mid-exec and the serial link drops before a clean
        # response comes back.  Helper returns True so the caller
        # polls for the new port.
        assert transport.reset_into_bootloader() is True

    def test_ensure_serial_failure_returns_false(self) -> None:
        def failing_factory(address: str, baudrate: int):
            raise OSError("port busy")

        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            transport_factory=failing_factory,
            runner=FakeRunner(),
        )
        assert transport.reset_into_bootloader() is False


class TestDeployFiles:
    """Tests for MicropythonTransport.deploy_files (Slice 1d)."""

    def _prepare_transport(
        self,
        *,
        mode: str = "mount",
        exec_output: bytes = b"entry ran\n",
        runner: FakeRunner | None = None,
    ) -> tuple[MicropythonTransport, FakeSerialTransport, FakeRunner]:
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        serial.exec_outputs = [(exec_output, b"")]
        runner = runner or FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode=mode,
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        return transport, serial, runner

    def test_mount_mode_writes_files_mounts_and_execs_entrypoint(
        self,
    ) -> None:
        transport, serial, _ = self._prepare_transport(mode="mount")
        try:
            output = transport.deploy_files(
                {"/code.py": b"print('hi')", "/lib/helper.py": b"X = 1"},
                "/code.py",
            )
            assert output == "entry ran\n"

            staging_dir = transport._staging_path
            assert staging_dir is not None
            assert (staging_dir / "code.py").read_bytes() == b"print('hi')"
            assert (staging_dir / "lib" / "helper.py").read_bytes() == b"X = 1"

            method_names = [call[0] for call in serial.calls]
            assert "mount_local" in method_names
            exec_call = next(call for call in serial.calls if call[0] == "exec_raw")
            script = exec_call[1][0]
            assert "/code.py" in script
            assert "exec(open" in script
        finally:
            transport.disconnect()

    def test_copy_mode_uses_mpremote_fs_cp_then_execs(self) -> None:
        transport, serial, runner = self._prepare_transport(mode="copy")
        try:
            transport.deploy_files(
                {"/code.py": b"print('hi')", "/lib/helper.py": b"X = 1"},
                "/code.py",
            )

            fs_cp_call = next(
                (call for call in runner.calls if "fs" in call[0]),
                None,
            )
            assert fs_cp_call is not None
            command = fs_cp_call[0]
            assert "cp" in command
            assert "-r" in command
            assert any(segment.endswith(":") for segment in command)

            exec_call = next(call for call in serial.calls if call[0] == "exec_raw")
            assert "/code.py" in exec_call[1][0]
        finally:
            transport.disconnect()

    def test_on_file_staged_called_per_file_in_sorted_order(self) -> None:
        transport, _, _ = self._prepare_transport()
        try:
            staged: list[str] = []
            transport.deploy_files(
                {"/lib/helper.py": b"X = 1", "/code.py": b"pass"},
                "/code.py",
                on_file_staged=staged.append,
            )
            assert staged == ["/code.py", "/lib/helper.py"]
        finally:
            transport.disconnect()

    def test_on_execute_line_emits_one_per_line(self) -> None:
        transport, serial, _ = self._prepare_transport()
        try:
            serial.exec_outputs = [(b"first\nsecond\nthird\n", b"")]
            lines: list[str] = []
            transport.deploy_files(
                {"/code.py": b"pass"}, "/code.py", on_execute_line=lines.append
            )
            assert lines == ["first", "second", "third"]
        finally:
            transport.disconnect()

    def test_entrypoint_missing_raises(self) -> None:
        transport, _, _ = self._prepare_transport()
        try:
            with pytest.raises(MicropythonTransportError, match="entrypoint"):
                transport.deploy_files({"/code.py": b"pass"}, "/missing.py")
        finally:
            transport.disconnect()

    def test_exec_raw_failure_wraps_error(self) -> None:
        transport, serial, _ = self._prepare_transport()
        try:
            serial.raise_on_execute = RuntimeError("link down")
            with pytest.raises(MicropythonTransportError, match="deploy-execute failed"):
                transport.deploy_files({"/code.py": b"pass"}, "/code.py")
        finally:
            transport.disconnect()

    def test_entrypoint_without_leading_slash_still_resolves(self) -> None:
        transport, serial, _ = self._prepare_transport()
        try:
            transport.deploy_files({"code.py": b"pass"}, "code.py")
            exec_call = next(call for call in serial.calls if call[0] == "exec_raw")
            script = exec_call[1][0]
            assert "/code.py" in script
        finally:
            transport.disconnect()

    def test_re_deploy_clears_prior_staging_and_mount(self) -> None:
        transport, serial, _ = self._prepare_transport(mode="mount")
        try:
            serial.exec_outputs = [(b"first\n", b""), (b"second\n", b"")]
            transport.deploy_files({"/code.py": b"one"}, "/code.py")
            first_staging = transport._staging_path
            transport.deploy_files({"/code.py": b"two"}, "/code.py")
            second_staging = transport._staging_path
            assert second_staging is not None
            assert (second_staging / "code.py").read_bytes() == b"two"
            # Prior staging directory was cleaned up (re-deploy creates a fresh tempdir).
            assert first_staging != second_staging
        finally:
            transport.disconnect()


class TestListFilesInScope:
    """MicroPython transport's diff-deploy scope listing primitive."""

    def test_returns_empty_in_mount_mode(self) -> None:
        """Mount-mode (RAM) deploys never wrote to flash → no scope listing."""
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="mount",
        )
        assert transport.list_files_in_scope() == []

    def test_copy_mode_parses_scope_marker_lines(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0",
            exec_outputs=[
                b"__CHU_F:/main.py\n__CHU_F:/lib/foo.py\n",
            ],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        result = transport.list_files_in_scope()
        assert sorted(result) == ["/lib/foo.py", "/main.py"]
        # The exec_raw call shipped the listing script.
        exec_calls = [call for call in serial.calls if call[0] == "exec_raw"]
        assert len(exec_calls) == 1
        assert "__CHU_F:" in exec_calls[0][1][0]

    def test_copy_mode_unmounts_before_listing(self) -> None:
        """If a mount is live (left over from a prior mode-mix), drop it first.

        Listing runs raw-REPL `os` calls; an active mount wraps the
        serial intercept and would garble I/O — matches the deploy_files
        + delete_files defensive pattern.
        """
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        # Force the transport into the "mounted" state.
        transport._serial = serial
        transport._mounted = True
        transport.list_files_in_scope()
        assert ("umount_local", ()) in serial.calls

    def test_copy_mode_exec_failure_raises(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0",
            raise_on_execute=RuntimeError("device dropped"),
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        with pytest.raises(MicropythonTransportError, match="list_files_in_scope"):
            transport.list_files_in_scope()


class TestDeleteFiles:
    """MicroPython transport's diff-deploy scope deletion primitive."""

    def test_empty_paths_no_op(self) -> None:
        """delete_files with no paths shouldn't open the serial transport."""
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="copy",
        )
        # No factory installed → if delete_files tried to open serial
        # it'd fail.  Confirm the empty-list path doesn't hit serial.
        transport.delete_files([])

    def test_mount_mode_no_op(self) -> None:
        """RAM mode never wrote to flash → nothing to delete."""
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="mount",
        )
        transport.delete_files(["/lib/foo.py"])

    def test_copy_mode_runs_remove_script(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        transport.delete_files(["/lib/old.py", "/active.py"])
        exec_calls = [call for call in serial.calls if call[0] == "exec_raw"]
        assert len(exec_calls) == 1
        script = exec_calls[0][1][0]
        # Both paths embedded in the script as a literal Python list.
        assert "/lib/old.py" in script
        assert "/active.py" in script
        assert "os.remove" in script

    def test_copy_mode_unmounts_before_delete(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        transport._serial = serial
        transport._mounted = True
        transport.delete_files(["/lib/old.py"])
        assert ("umount_local", ()) in serial.calls

    def test_copy_mode_exec_failure_raises(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0",
            raise_on_execute=RuntimeError("dropped"),
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        with pytest.raises(MicropythonTransportError, match="delete_files"):
            transport.delete_files(["/lib/old.py"])


class TestWipeFilesystem:
    """`wipe_filesystem()` walks `/` and removes every file + directory."""

    def test_mount_mode_no_op(self) -> None:
        """RAM/mount mode never wrote to flash → wipe is a silent no-op."""
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="mount",
        )
        # No factory installed → if wipe tried to open serial it'd fail.
        transport.wipe_filesystem()

    def test_copy_mode_runs_wipe_script(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        transport.wipe_filesystem()
        exec_calls = [call for call in serial.calls if call[0] == "exec_raw"]
        assert len(exec_calls) == 1
        script = exec_calls[0][1][0]
        # Recursive walker that removes every file via os.remove.
        assert "_rmrf" in script
        assert "os.remove" in script
        assert "_rmrf('/')" in script

    def test_copy_mode_unmounts_before_wipe(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        transport._serial = serial
        transport._mounted = True
        transport.wipe_filesystem()
        assert ("umount_local", ()) in serial.calls

    def test_copy_mode_exec_failure_raises(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0",
            raise_on_execute=RuntimeError("dropped"),
        )
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        with pytest.raises(MicropythonTransportError, match="wipe_filesystem"):
            transport.wipe_filesystem()
