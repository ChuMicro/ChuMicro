"""Tests for MicropythonTransport — persistent serial + subprocess fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from chumicro_deploy.micropython_transport import (
    _EXECUTE_IDLE_TIMEOUT,
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
class FakeSerialPort:
    """Records raw byte writes against the pyserial-port surface.

    The MP transport's soft-reboot path uses
    ``self._serial.serial.write(b"...")`` for direct Ctrl-B + Ctrl-D
    writes that mpremote's higher-level helpers don't expose.  Tests
    that exercise that path assert on :attr:`writes`.
    """

    writes: list[bytes] = field(default_factory=list)

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)


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
    # Successive ``read_until`` return values, in call order.  Bare bytes
    # only — the real ``read_until`` returns bytes; tests pass the full
    # captured-output payload for each soft-reboot read.
    read_until_outputs: list[bytes] = field(default_factory=list)
    raise_on_execute: Exception | None = None
    calls: list[tuple[str, tuple]] = field(default_factory=list)
    serial: FakeSerialPort = field(default_factory=FakeSerialPort)

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

    def read_until(
        self,
        min_num_bytes: int,
        ending: bytes,
        timeout: float = 10,
        timeout_overall: float | None = None,
    ) -> bytes:
        self.calls.append(("read_until", (min_num_bytes, ending, timeout, timeout_overall)))
        if self.read_until_outputs:
            return self.read_until_outputs.pop(0)
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

    def test_stage_skips_host_only_build_artifacts(self, tmp_path) -> None:
        """``__pycache__``, ``*.pyc``, and ``*.egg-info`` must not deploy.

        Regression: a pytest run on host populates ``__pycache__/``
        next to every source file with CPython 3.x bytecode; an
        editable install creates ``*.egg-info`` metadata.  Without
        the exclude filter, ``mpremote fs cp -r`` flashes both,
        and a Pi Pico W MP fills its ~860 KB filesystem on the
        wifi+sockets+requests stack alone — even though the actual
        library source totals ~240 KB.
        """
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        package_dir = source_dir / "chumicro_example"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "module.py").write_text("# module")

        # Cruft that should NOT deploy.
        pycache = package_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-314.pyc").write_bytes(b"\x00" * 1024)
        (source_dir / "chumicro_example.egg-info").mkdir()
        (source_dir / "chumicro_example.egg-info" / "PKG-INFO").write_text("noise")
        (package_dir / ".DS_Store").write_bytes(b"\x00")
        (package_dir / "stale.pyc").write_bytes(b"\x00")

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

        staged = transport._staging_path
        assert staged is not None
        assert (staged / "chumicro_example" / "module.py").exists()
        assert not (staged / "chumicro_example" / "__pycache__").exists()
        assert not (staged / "chumicro_example.egg-info").exists()
        assert not (staged / "chumicro_example" / ".DS_Store").exists()
        assert not (staged / "chumicro_example" / "stale.pyc").exists()

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

    def test_execute_uses_long_idle_timeout(self, tmp_path) -> None:
        """execute() must pass ``_EXECUTE_IDLE_TIMEOUT`` to ``exec_raw``.

        Regression: a previous fixed ``timeout=120`` fired mid-bisection
        on the on-device fragmentation tests on Lolin S2 MP (2 MB heap),
        surfacing as ``TransportError: timeout waiting for first EOF
        reception``.  mpremote's ``exec_raw(timeout=N)`` is an
        idle-between-bytes timeout, not wall-clock — so the value needs
        to cover the longest stretch of pure on-device silence (the
        histogram tier probe's tight allocation loop plus surrounding
        ``gc.collect()`` calls).
        """
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(
            address="/dev/ttyUSB0",
            exec_outputs=[b""],
        )
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_dir], [], harness_dir)

        transport.execute("import test_example")

        exec_calls = [args for name, args in serial.calls if name == "exec_raw"]
        assert len(exec_calls) == 1
        _command, timeout = exec_calls[0]
        assert timeout == _EXECUTE_IDLE_TIMEOUT

        transport.disconnect()

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
    """Tests for MicropythonTransport.deploy_files."""

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

    def test_copy_mode_default_clean_false_does_not_wipe_lib(self) -> None:
        """``clean=False`` (the default) leaves ``:/lib`` untouched.

        Mirrors the CP transport's additive-by-default contract that
        ``chumicro-workspace deploy`` relies on — users who hand-install
        deps via ``mpremote mip install`` keep them across deploys.
        """
        transport, _, runner = self._prepare_transport(mode="copy")
        try:
            transport.deploy_files(
                {"/code.py": b"print('hi')", "/lib/helper.py": b"X = 1"},
                "/code.py",
            )
            rm_calls = [
                call for call in runner.calls
                if "rm" in call[0] and ":/lib" in call[0]
            ]
            assert rm_calls == []
        finally:
            transport.disconnect()

    def test_copy_mode_clean_true_wipes_lib_before_push(self) -> None:
        """``clean=True`` issues ``mpremote fs rm -r :/lib`` before the push.

        Mirrors the CP transport's ``rsync --delete`` semantics for
        the most common accumulation site (chumicro_* and other
        library packages under ``/lib``).  The ordering matters —
        wiping AFTER the push would clobber the just-deployed payload.
        """
        transport, _, runner = self._prepare_transport(mode="copy")
        try:
            transport.deploy_files(
                {"/code.py": b"print('hi')", "/lib/helper.py": b"X = 1"},
                "/code.py",
                clean=True,
            )
            rm_index = next(
                (
                    index for index, call in enumerate(runner.calls)
                    if "rm" in call[0] and ":/lib" in call[0]
                ),
                None,
            )
            cp_index = next(
                (
                    index for index, call in enumerate(runner.calls)
                    if "cp" in call[0] and "-r" in call[0]
                ),
                None,
            )
            assert rm_index is not None, (
                f"expected fs rm -r :/lib call; got {runner.calls!r}"
            )
            assert cp_index is not None, (
                f"expected fs cp -r call; got {runner.calls!r}"
            )
            assert rm_index < cp_index, (
                "lib wipe must precede the staging push so the push "
                "isn't clobbered"
            )
        finally:
            transport.disconnect()

    def test_copy_mode_clean_true_tolerates_missing_lib_dir(self) -> None:
        """First-deploy case: ``:/lib`` doesn't exist yet — rm fails;
        deploy still proceeds and pushes the staging tree.

        mpremote exits non-zero on ``rm -r`` against a missing path.
        Without the swallow, every first-clean-deploy on a freshly
        formatted board would raise ``MicropythonTransportError``
        before any payload reached flash.
        """
        rm_failure = FakeSubprocessResult(
            returncode=1, stderr="rm: cannot stat ':/lib': No such file",
        )
        success = FakeSubprocessResult()
        # ``deploy_files`` copy-mode mpremote sequence: fs rm -r :/lib
        # (failure) → fs cp -r staging :/. (success).  No other
        # mpremote calls fire on this path.
        runner = FakeRunner(results=[rm_failure, success])
        transport, _, _ = self._prepare_transport(mode="copy", runner=runner)
        try:
            # Should NOT raise even though rm failed.
            transport.deploy_files(
                {"/code.py": b"print('hi')"},
                "/code.py",
                clean=True,
            )
            cp_calls = [
                call for call in runner.calls
                if "cp" in call[0] and "-r" in call[0]
            ]
            assert cp_calls, (
                "fs cp -r push must still fire when fs rm fails — "
                f"got {runner.calls!r}"
            )
        finally:
            transport.disconnect()

    def test_mount_mode_clean_kwarg_is_no_op(self) -> None:
        """Mount mode never writes to device flash, so ``clean`` is a no-op.

        ``mpremote mount_local`` is transient — the staging tree is
        host-side and unmounts cleanly on disconnect.  There's no
        accumulation to wipe and no ``mpremote fs rm`` call should
        fire.
        """
        transport, _, runner = self._prepare_transport(mode="mount")
        try:
            transport.deploy_files(
                {"/code.py": b"print('hi')"},
                "/code.py",
                clean=True,
            )
            rm_calls = [
                call for call in runner.calls
                if "rm" in call[0] and ":/lib" in call[0]
            ]
            assert rm_calls == []
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

    def test_deploy_files_uses_long_idle_timeout(self) -> None:
        """``deploy_files`` execs the entrypoint with ``_EXECUTE_IDLE_TIMEOUT``.

        Same regression as ``test_execute_uses_long_idle_timeout`` — the
        on-device fragmentation tests run their entrypoint via
        ``deploy_files``, so this path also has to give the histogram
        bisection enough idle headroom.
        """
        transport, serial, _ = self._prepare_transport()
        try:
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")
            exec_call = next(call for call in serial.calls if call[0] == "exec_raw")
            _script, timeout = exec_call[1]
            assert timeout == _EXECUTE_IDLE_TIMEOUT
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


class TestDeployFilesSoftReboot:
    """``follow="soft_reboot"`` mode — analog of CP's flash-mode pattern.

    The MicroPython flash transport adopts CP's soft-reboot read for
    app-code deploys whose entrypoint may be a ``while True`` body
    that never returns — without that, the deploy would block waiting
    for the entrypoint to exit before reading any output.
    """

    def _prepare(
        self,
        *,
        captured_serial: bytes,
        runner: FakeRunner | None = None,
        timeout: float = 0.1,
    ) -> tuple[MicropythonTransport, FakeSerialTransport, FakeRunner]:
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        # Two read_until calls: first waits for the friendly-REPL
        # prompt (`>>> `) after Ctrl-B exits raw REPL — the prompt
        # itself is enough to satisfy the read; second captures
        # boot.py + main.py output after Ctrl-D soft-reboot.
        serial.read_until_outputs = [b">>> ", captured_serial]
        runner = runner or FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="copy",
            timeout=timeout,
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        return transport, serial, runner

    def test_writes_ctrl_b_then_ctrl_d_and_reads_until_prompt(self) -> None:
        """Soft-reboot path sends Ctrl-B + Ctrl-D, reads until ``>>>``."""
        captured = (
            b"MPY: soft reboot\r\n"
            b"WIFI_OK ip=10.0.0.5\r\n"
            b"NTP_OK 1700000000\r\n"
            b"MicroPython v1.28.0 on 2026-04-06; ...\r\n"
            b'Type "help()" for more information.\r\n'
            b">>> "
        )
        transport, serial, _ = self._prepare(captured_serial=captured)
        try:
            output = transport.deploy_files(
                {"/main.py": b"print('hi')"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        # Direct serial bytes — Ctrl-B (\r\x02), then (after waiting
        # for the friendly-REPL prompt to appear) Ctrl-D (\x04).
        assert serial.serial.writes == [b"\r\x02", b"\x04"]
        # Two read_until calls: prompt-sync (after Ctrl-B), then
        # soft-reboot capture (after Ctrl-D).
        read_calls = [call for call in serial.calls if call[0] == "read_until"]
        assert len(read_calls) == 2
        _min, ending, _t, _to = read_calls[0][1]
        assert ending == b">>> "
        _min, ending, timeout, timeout_overall = read_calls[1][1]
        assert ending == b"\r\n>>> "
        assert timeout == 0.1
        assert timeout_overall == 0.1
        # Output trimmed to the user-visible portion.  Internal \r\n
        # is preserved (matches CircuitpythonTransport._extract_code_output);
        # `splitlines()` consumers handle both line endings.
        assert output == "WIFI_OK ip=10.0.0.5\r\nNTP_OK 1700000000\n"

    def test_no_exec_raw_in_soft_reboot_mode(self) -> None:
        """Soft-reboot mode bypasses the raw-REPL exec entirely."""
        transport, serial, _ = self._prepare(
            captured_serial=b"MPY: soft reboot\r\nhi\r\n",
        )
        try:
            transport.deploy_files(
                {"/main.py": b"print('hi')"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        assert not any(call[0] == "exec_raw" for call in serial.calls)

    def test_partial_output_returned_when_prompt_never_appears(self) -> None:
        """``while True`` body — no prompt, partial output returned verbatim."""
        captured = b"MPY: soft reboot\r\ntick 1\r\ntick 2\r\ntick 3\r\n"
        transport, _, _ = self._prepare(captured_serial=captured)
        try:
            output = transport.deploy_files(
                {"/main.py": b"while True: pass"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        # No friendly-REPL banner cut: read_until timed out, output
        # stops at whatever accumulated.  Internal \r\n preserved.
        assert output == "tick 1\r\ntick 2\r\ntick 3\n"

    def test_traceback_preserved_in_output(self) -> None:
        """Exceptions in main.py — traceback kept, post-traceback banner stripped."""
        captured = (
            b"MPY: soft reboot\r\n"
            b"Traceback (most recent call last):\r\n"
            b'  File "main.py", line 5, in <module>\r\n'
            b"NameError: name 'undefined' is not defined\r\n"
            b"MicroPython v1.28.0 on 2026-04-06; ...\r\n"
            b'Type "help()" for more information.\r\n'
            b">>> "
        )
        transport, _, _ = self._prepare(captured_serial=captured)
        try:
            output = transport.deploy_files(
                {"/main.py": b"undefined"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        assert "Traceback" in output
        assert "NameError" in output
        assert "MicroPython v" not in output  # banner stripped
        assert ">>>" not in output             # prompt stripped

    def test_pre_reboot_buffer_discarded(self) -> None:
        """Stale bytes before ``MPY: soft reboot`` are dropped."""
        captured = (
            b"leftover from previous run\r\n"
            b"MPY: soft reboot\r\n"
            b"REAL_OUTPUT\r\n"
            b"MicroPython v1.28.0 on 2026-04-06; ...\r\n"
            b">>> "
        )
        transport, _, _ = self._prepare(captured_serial=captured)
        try:
            output = transport.deploy_files(
                {"/main.py": b"print('REAL_OUTPUT')"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        assert "leftover" not in output
        assert output == "REAL_OUTPUT\n"

    def test_on_execute_line_called_per_line(self) -> None:
        """``on_execute_line`` callback fires for each captured line."""
        captured = b"MPY: soft reboot\r\nA\r\nB\r\nC\r\n>>> "
        transport, _, _ = self._prepare(captured_serial=captured)
        try:
            seen: list[str] = []
            transport.deploy_files(
                {"/main.py": b"pass"},
                "/main.py",
                follow="soft_reboot",
                on_execute_line=seen.append,
            )
        finally:
            transport.disconnect()

        assert seen == ["A", "B", "C"]

    def test_on_file_staged_still_fires(self) -> None:
        """Staging-side callbacks unchanged in soft-reboot mode."""
        captured = b"MPY: soft reboot\r\n>>> "
        transport, _, _ = self._prepare(captured_serial=captured)
        try:
            staged: list[str] = []
            transport.deploy_files(
                {"/main.py": b"pass", "/lib/helper.py": b"X = 1"},
                "/main.py",
                follow="soft_reboot",
                on_file_staged=staged.append,
            )
        finally:
            transport.disconnect()

        assert staged == ["/lib/helper.py", "/main.py"]

    def test_mount_mode_rejected(self) -> None:
        """``follow="soft_reboot"`` requires ``mode="copy"``."""
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            transport_factory=_factory_for(serial),
        )
        with pytest.raises(MicropythonTransportError, match="mode='copy'"):
            transport.deploy_files(
                {"/main.py": b"pass"},
                "/main.py",
                follow="soft_reboot",
            )

    def test_non_main_py_entrypoint_rejected(self) -> None:
        """``follow="soft_reboot"`` requires entrypoint ``/main.py``."""
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        with pytest.raises(MicropythonTransportError, match="/main.py"):
            transport.deploy_files(
                {"/code.py": b"pass"},
                "/code.py",
                follow="soft_reboot",
            )

    def test_does_not_re_enter_raw_repl_after_read(self) -> None:
        """Soft-reboot mode must not re-enter raw REPL — would Ctrl-C main.py.

        Mirror of CP's flash-mode rule: leave the board in friendly
        REPL with the entrypoint running.  mpremote's enter_raw_repl
        sends Ctrl-C × 2 + Ctrl-A, which would kill any ``while True``
        loop the entrypoint just started.  Subsequent transport ops
        re-enter raw REPL on demand via _ensure_serial.
        """
        captured = b"MPY: soft reboot\r\n>>> "
        transport, serial, _ = self._prepare(captured_serial=captured)
        try:
            transport.deploy_files(
                {"/main.py": b"pass"},
                "/main.py",
                follow="soft_reboot",
            )
        finally:
            transport.disconnect()

        # The only enter_raw_repl call should be the one _ensure_serial
        # made before deploy_files.  No post-read enter_raw_repl call
        # is allowed — that would Ctrl-C the just-started main.py.
        enter_calls = [call for call in serial.calls if call[0] == "enter_raw_repl"]
        post_read_enters = [
            call for call in enter_calls
            # Earlier, _ensure_serial ran; we just need to ensure no call
            # appears AFTER the soft-reboot read_until.  Order check via
            # index: any enter_raw_repl after the second read_until is wrong.
            if serial.calls.index(call)
            > max(
                idx for idx, prior in enumerate(serial.calls)
                if prior[0] == "read_until"
            )
        ]
        assert post_read_enters == []


class TestExtractMainPyOutput:
    """Direct unit coverage of the static trim helper."""

    def test_returns_just_user_output_when_main_returned(self) -> None:
        raw = (
            b"MPY: soft reboot\r\n"
            b"hello\r\n"
            b"MicroPython v1.28.0 on ...\r\n"
            b">>> "
        )
        assert MicropythonTransport._extract_main_py_output(raw) == "hello\n"

    def test_returns_partial_output_when_no_banner(self) -> None:
        raw = b"MPY: soft reboot\r\ntick 1\r\ntick 2\r\n"
        assert (
            MicropythonTransport._extract_main_py_output(raw)
            == "tick 1\r\ntick 2\n"
        )

    def test_returns_empty_string_with_only_marker(self) -> None:
        raw = b"MPY: soft reboot\r\n"
        assert MicropythonTransport._extract_main_py_output(raw) == "\n"

    def test_no_marker_returns_raw_text(self) -> None:
        # Genuinely no soft-reboot ever observed (read pre-empted, etc.).
        # We don't sync — return whatever we got, stripped.
        raw = b"random bytes\r\nmore\r\n"
        assert (
            MicropythonTransport._extract_main_py_output(raw)
            == "random bytes\r\nmore\n"
        )


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


class TestClearEntrypoints:
    """MP transport's pre-soft-reset entrypoint clear (sweep race fix)."""

    def test_mount_mode_no_op(self) -> None:
        """Mount (RAM) mode never persists an entrypoint to clear."""
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="mount",
        )
        transport.clear_entrypoints()  # no serial opened, no raise

    def test_copy_mode_removes_and_verifies_entrypoints(self) -> None:
        serial = FakeSerialTransport("/dev/ttyUSB0", exec_outputs=[b""])
        runner = FakeRunner()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
        )
        transport.clear_entrypoints()
        exec_calls = [call for call in serial.calls if call[0] == "exec_raw"]
        assert len(exec_calls) == 1
        script = exec_calls[0][1][0]
        # Device-side remove + re-stat (authoritative; no host FAT lag).
        assert "main.py" in script
        assert "code.py" in script
        assert "os.remove" in script
        assert "os.stat" in script

    def test_copy_mode_raises_on_exec_failure(self) -> None:
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
        with pytest.raises(
            MicropythonTransportError, match="clear_entrypoints",
        ):
            transport.clear_entrypoints()


class _RecordingTime:
    """Fake ``time`` source — records sleep durations, no wall-clock wait."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self._now: float = 0.0

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds

    def monotonic(self) -> float:
        return self._now


class TestWipeFilesystem:
    """`wipe_filesystem()` reformats LittleFS via substrate-dispatched mkfs."""

    def test_mount_mode_no_op(self) -> None:
        """RAM/mount mode never wrote to flash → wipe is a silent no-op."""
        runner = FakeRunner()
        recorder = _RecordingTime()
        transport = MicropythonTransport(
            "/dev/ttyUSB0", runner=runner, mode="mount", time=recorder,
        )
        # No factory installed → if wipe tried to open serial it'd fail.
        transport.wipe_filesystem()
        assert runner.calls == []
        assert recorder.sleeps == []

    def test_copy_mode_runs_mkfs_script_via_subprocess(self) -> None:
        runner = FakeRunner()
        recorder = _RecordingTime()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            time=recorder,
        )
        transport.wipe_filesystem()
        assert len(runner.calls) == 1
        command, _kwargs = runner.calls[0]
        # mpremote exec — last arg is the script.
        assert "exec" in command
        script = command[-1]
        # Substrate dispatch on sys.platform with both supported MP boards.
        assert "sys.platform == 'rp2'" in script
        assert "sys.platform == 'esp32'" in script
        # rp2 → rp2.Flash() ; esp32 → vfs partition lookup.
        assert "rp2.Flash()" in script
        assert "esp32.Partition.find" in script
        assert "label='vfs'" in script
        # Must umount before mkfs and soft_reset after.
        assert "os.umount('/')" in script
        assert "os.VfsLfs2.mkfs" in script
        assert "machine.soft_reset()" in script
        # Other substrates must raise rather than silently no-op.
        assert "RuntimeError" in script
        # Settle before any next call grabs the serial port.
        assert recorder.sleeps == [2.0]

    def test_copy_mode_unmounts_before_wipe(self) -> None:
        serial = FakeSerialTransport(
            "/dev/ttyUSB0", exec_outputs=[b""],
        )
        runner = FakeRunner()
        recorder = _RecordingTime()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            transport_factory=_factory_for(serial),
            time=recorder,
        )
        transport._serial = serial
        transport._mounted = True
        transport.wipe_filesystem()
        # umount_local is called before the persistent serial is closed.
        assert ("umount_local", ()) in serial.calls
        # Persistent serial closed (so mpremote subprocess can grab the port).
        assert ("close", ()) in serial.calls
        # Then the subprocess runs the mkfs script.
        assert len(runner.calls) == 1

    def test_copy_mode_exec_failure_raises(self) -> None:
        runner = FakeRunner(
            results=[FakeSubprocessResult(returncode=1, stderr="device busy")]
        )
        recorder = _RecordingTime()
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            runner=runner,
            mode="copy",
            time=recorder,
        )
        with pytest.raises(MicropythonTransportError, match="wipe_filesystem"):
            transport.wipe_filesystem()
        # Failure path skips the post-reset settle.
        assert recorder.sleeps == []


class TestRuntimeFiltering:
    """Wrong-runtime files never land in MP staging."""

    def _build_dual_runtime_pkg(self, source_root: Path) -> None:
        pkg = source_root / "chumicro_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# universal\n")
        adapters = pkg / "_adapters"
        adapters.mkdir()
        (adapters / "__init__.py").write_text("")
        (adapters / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (adapters / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

    def test_target_runtime_default_is_micropython(self) -> None:
        """Selecting :class:`MicropythonTransport` *is* targeting MP."""
        transport = MicropythonTransport("/dev/ttyUSB0", runner=FakeRunner())
        assert transport._target_runtime == "micropython"

    def test_stage_excludes_circuitpython_files(self, tmp_path: Path) -> None:
        source_root = tmp_path / "src"
        source_root.mkdir()
        self._build_dual_runtime_pkg(source_root)
        harness = tmp_path / "harness"
        harness.mkdir()

        runner = FakeRunner()
        serial = FakeSerialTransport(address="/dev/ttyUSB0")
        transport = MicropythonTransport(
            "/dev/ttyUSB0",
            mode="mount",
            runner=runner,
            transport_factory=_factory_for(serial),
        )
        transport.stage([source_root], test_files=[], harness_source=harness)

        staging = transport._staging_path
        assert staging is not None
        adapters = staging / "chumicro_pkg" / "_adapters"
        assert (adapters / "mp.py").exists()
        assert not (adapters / "cp.py").exists()

        transport.disconnect()
