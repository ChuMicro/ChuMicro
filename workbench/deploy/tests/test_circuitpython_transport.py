"""Tests for CircuitpythonTransport, the pyserial raw REPL transport."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest
from chumicro_deploy import DeviceImplementation
from chumicro_deploy.circuitpy_drive import (
    _circuitpy_volume_candidates,
    _format_probe_error,
)
from chumicro_deploy.circuitpython_transport import (
    _CTRL_A,
    _CTRL_C,
    _CTRL_D,
    _RAW_REPL_PROMPT,
    _WIPE_FAT_REMOUNT_TIMEOUT_SECONDS,
    CircuitpythonTransport,
    CircuitpythonTransportError,
    PostStageStep,
)
from chumicro_deploy.testing import (
    FakeSerialPort,
    FakeTime,
    isolate_from_host_filesystem,
)

#: Shorthand for the standard autoreload REPL acknowledgment.
_OK_RESPONSE = b"OK\x04\x04>"

#: Test-only board identity used by :func:`_plant_verifiable_circuitpy`.
#: Keeps the boot_out.txt content and the probe-response bytes in sync.
_TEST_BOOT_MACHINE = "TestBoard with rp2040"
_TEST_BOOT_UID = "DEADBEEF"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test in this file hermetic from the macOS host.

    Without this: on a dev box with a real CIRCUITPY board plugged in,
    tests that don't explicitly pass ``drive_path`` + ``monkeypatch``
    will (a) probe-write+unlink files onto the real device's filesystem
    and (b) block on real macOS ``sync`` / ``xattr`` / ``dot_clean``
    subprocess calls.  See
    :func:`chumicro_deploy.testing.isolate_from_host_filesystem`.

    Tests that need ``_circuitpy_volume_candidates`` to return a specific
    path can still call ``monkeypatch.setattr`` with their own value.
    Function-scoped monkeypatches override earlier ones.
    """
    isolate_from_host_filesystem(monkeypatch)


def _repl_response(stdout: bytes = b"", stderr: bytes = b"") -> bytes:
    """Build a raw-REPL response with *stdout* / *stderr* payloads."""
    return b"OK" + stdout + b"\x04" + stderr + b"\x04>"


def _plant_verifiable_circuitpy(
    drive: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set up *drive* so ``_verify_drive_for_board`` cheap-paths.

    Plants a ``boot_out.txt`` on *drive* with the standard
    ``_TEST_BOOT_UID`` / ``_TEST_BOOT_MACHINE`` identity, and patches
    ``CircuitpythonTransport.probe_implementation`` to return a
    matching :class:`DeviceImplementation` without touching the fake
    serial port.  Tests that aren't exercising verify itself get
    cheap-path-passes without having to queue probe response bytes
    in their fake-port read sequence.

    Verify-specific tests (``TestDriveVerification``,
    ``TestListFilesInScopeAndDelete``'s auto-correct cases) bypass
    this helper.  They need the real probe roundtrip + their own
    boot_out.txt content to exercise the mismatch / auto-correct
    code paths.
    """
    drive.mkdir(exist_ok=True)
    (drive / "boot_out.txt").write_text(
        f"Adafruit CircuitPython 10.2.0 on 2026-01-01; {_TEST_BOOT_MACHINE}\n"
        f"Board ID:test_board\n"
        f"UID:{_TEST_BOOT_UID}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        CircuitpythonTransport,
        "probe_implementation",
        lambda self: DeviceImplementation(
            name="circuitpython",
            version="10.2.0",
            machine=_TEST_BOOT_MACHINE,
            uid=_TEST_BOOT_UID,
        ),
    )


class TestConnect:
    """Tests for CircuitpythonTransport.connect."""

    def test_connect_sends_interrupt_and_enters_raw_repl(self) -> None:
        """connect() should send Ctrl-C×2 then Ctrl-A."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        # Should have written: Ctrl-C, Ctrl-C, Ctrl-A
        assert _CTRL_C in port.writes
        assert _CTRL_A in port.writes
        ctrl_c_count = sum(1 for write in port.writes if write == _CTRL_C)
        assert ctrl_c_count == 2

    def test_connect_raises_on_port_open_failure(self) -> None:
        """connect() should raise when the serial port cannot be opened."""
        port = FakeSerialPort(open_error=OSError("port not found"))

        transport = CircuitpythonTransport(
            "/dev/ttyNONE",
            serial_port_factory=port,
            time=FakeTime(),
        )

        with pytest.raises(
            CircuitpythonTransportError,
            match="Failed to open serial port",
        ):
            transport.connect()

    def test_connect_raises_when_no_raw_repl_prompt(self) -> None:
        """connect() should raise when raw REPL prompt is not received."""
        port = FakeSerialPort(read_responses=[b"some other output"])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )

        with pytest.raises(
            CircuitpythonTransportError,
            match="Did not receive raw REPL prompt",
        ):
            transport.connect()

    def test_connect_uses_configured_baudrate(self) -> None:
        """connect() should pass the baudrate to the serial port factory."""
        captured_kwargs = {}
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        def recording_factory(**kwargs):
            captured_kwargs.update(kwargs)
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            baudrate=9600,
            serial_port_factory=recording_factory,
            time=FakeTime(),
        )
        transport.connect()

        assert captured_kwargs.get("baudrate") == 9600

    def test_default_factory_requests_exclusive_port_lock(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The default pyserial factory passes ``exclusive=True``.

        Regression guard for the port-locking fix: dropping the kwarg
        lets two host processes share one ``/dev/cu.usbmodem...`` and
        garble each other's raw-REPL session.  Patches ``serial.Serial``
        and calls the default factory directly so the assertion sees the
        kwargs the production code path would send to pyserial.
        """
        captured_kwargs: dict[str, object] = {}

        def fake_serial(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return object()

        import serial

        monkeypatch.setattr(serial, "Serial", fake_serial)
        CircuitpythonTransport._default_serial_factory(
            port="/dev/ttyUSB0", baudrate=115200, timeout=1.0,
        )

        assert captured_kwargs.get("exclusive") is True
        assert captured_kwargs.get("port") == "/dev/ttyUSB0"


class TestStage:
    """Tests for CircuitpythonTransport.stage."""

    def test_stage_collects_package_sources(self, tmp_path: Path) -> None:
        """stage() should read .py files and store as module entries."""
        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "ticks.py").write_text("def ticks_ms(): pass")

        harness_dir = tmp_path / "harness"
        harness_package = harness_dir / "chumicro_test_harness"
        harness_package.mkdir(parents=True)
        (harness_package / "__init__.py").write_text("# harness init")
        (harness_package / "runner.py").write_text("def run_module(): pass")

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [test_file], harness_dir)

        assert transport.staged_sources is not None
        module_names = [name for name, _ in transport.staged_sources]
        assert "chumicro_timing" in module_names
        assert "chumicro_timing.ticks" in module_names
        assert "chumicro_test_harness" in module_names
        assert "chumicro_test_harness.runner" in module_names

        transport.disconnect()

    def test_stage_ignores_non_package_directories(
        self, tmp_path: Path,
    ) -> None:
        """stage() should skip directories without __init__.py."""
        source_dir = tmp_path / "src"
        non_package = source_dir / "not_a_package"
        non_package.mkdir(parents=True)
        (non_package / "something.py").write_text("# not a package")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        assert transport.staged_sources == []

        transport.disconnect()

    def test_stage_skips_plain_files_in_source_dir(
        self, tmp_path: Path,
    ) -> None:
        """stage() should skip plain files at the top of source dirs."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        # A plain .py file at src/ level (not inside a package dir).
        (source_dir / "stray_file.py").write_text("# stray")
        # A real package.
        package_dir = source_dir / "mypkg"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("# init")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        module_names = [name for name, _ in transport.staged_sources]
        assert "mypkg" in module_names
        # stray_file should NOT appear.
        assert not any("stray" in name for name in module_names)

        transport.disconnect()

    def test_stage_handles_missing_source_dir(self, tmp_path: Path) -> None:
        """stage() should handle non-existent source directories."""
        nonexistent = tmp_path / "does_not_exist"
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([nonexistent], [], harness_dir)

        assert transport.staged_sources == []

        transport.disconnect()

    def test_stage_collects_nested_subpackages(
        self, tmp_path: Path,
    ) -> None:
        """stage() should recursively collect subpackage modules."""
        source_dir = tmp_path / "src"
        package_dir = source_dir / "mypkg"
        subpackage_dir = package_dir / "sub"
        subpackage_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# pkg init")
        (subpackage_dir / "__init__.py").write_text("# sub init")
        (subpackage_dir / "helper.py").write_text("x = 1")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        module_names = [name for name, _ in transport.staged_sources]
        assert "mypkg" in module_names
        assert "mypkg.sub" in module_names
        assert "mypkg.sub.helper" in module_names

        transport.disconnect()


class TestExecute:
    """Tests for CircuitpythonTransport.execute."""

    def test_execute_sends_code_and_ctrl_d(self, tmp_path: Path) -> None:
        """execute() should send the bootstrap code followed by Ctrl-D."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        execute_response = b"OKPASS test_ok (0.001s)\n\x04\x04>"
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                execute_response,   # execute
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        output = transport.execute("print('hello')")

        # The code bytes and Ctrl-D should have been written.
        assert b"print('hello')" in port.writes
        assert _CTRL_D in port.writes
        assert output == "PASS test_ok (0.001s)\n"

        transport.disconnect()

    def test_execute_raises_on_stderr(self, tmp_path: Path) -> None:
        """execute() should raise when stderr contains error output."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        execute_response = b"OK\x04NameError: name 'x' is not defined\x04>"
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, execute_response],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        with pytest.raises(
            CircuitpythonTransportError,
            match="CircuitPython reported an error",
        ):
            transport.execute("print(x)")

        transport.disconnect()

    def test_execute_raises_when_no_ok_prefix(
        self, tmp_path: Path,
    ) -> None:
        """execute() should raise when response doesn't start with OK."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, b"ERROR\x04\x04>"],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        with pytest.raises(
            CircuitpythonTransportError,
            match="Raw REPL did not acknowledge",
        ):
            transport.execute("bad code")

        transport.disconnect()

    def test_execute_with_single_marker_extracts_stdout(
        self, tmp_path: Path,
    ) -> None:
        """execute() with one \\x04 should extract stdout correctly."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Single \x04 followed by ">", valid but minimal response.
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, b"OKhello\x04\x04>"],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        output = transport.execute("some code")
        assert output == "hello"

        transport.disconnect()

    def test_execute_before_stage_raises(self) -> None:
        """execute() without prior stage() should raise."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        with pytest.raises(
            CircuitpythonTransportError,
            match="stage",
        ):
            transport.execute("print('hello')")

        transport.disconnect()

    def test_execute_before_connect_raises(self) -> None:
        """execute() without prior connect() should raise."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )
        # Bypass the stage-called guard so execute() surfaces the
        # connect-required error instead.
        transport._staged = True

        with pytest.raises(
            CircuitpythonTransportError,
            match="connect",
        ):
            transport.execute("print('hello')")


class TestExecuteOnLineDispatch:
    """``on_line`` dispatches stdout lines live, as raw-REPL bytes arrive."""

    def test_execute_dispatches_each_line_as_bytes_land(
        self, tmp_path: Path,
    ) -> None:
        """Two serial read chunks each carrying their own line dispatches
        on_line for each, in arrival order, with the ``OK`` envelope and
        ``\\x04`` terminator both stripped from the callback's view."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OKline-a\n",
                b"line-b\nline-c\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        lines: list[str] = []
        output = transport.execute(
            "print('streaming')", on_line=lines.append,
        )

        assert lines == ["line-a", "line-b", "line-c"]
        assert output == "line-a\nline-b\nline-c\n"

        transport.disconnect()

    def test_execute_scripts_dispatches_lines_across_chunks(
        self, tmp_path: Path,
    ) -> None:
        """A two-script chunked execute threads ``on_line`` through each
        execute call, dispatching every script's stdout in order."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OKfrom-chunk-one\n\x04\x04>",
                b"OK\x04\x04>",
                b"OKfrom-chunk-two\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        lines: list[str] = []
        transport.execute_scripts(
            ["print('chunk one')", "print('chunk two')"],
            on_line=lines.append,
        )

        assert lines == ["from-chunk-one", "from-chunk-two"]

        transport.disconnect()


class TestExecuteScripts:
    """Tests for chunked raw-REPL execution."""

    def test_execute_scripts_runs_each_chunk_and_returns_last_output(
        self, tmp_path: Path,
    ) -> None:
        """execute_scripts() should run every chunk and return the final stdout."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OK\x04\x04>",
                b"OK\x04\x04>",
                b"OKPASS test_ok (0.001s)\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        output = transport.execute_scripts([
            "print('chunk one')",
            "print('chunk two')",
        ])

        assert output == "PASS test_ok (0.001s)\n"
        written_data = b"".join(port.writes)
        assert b"gc.collect()" in written_data

        transport.disconnect()

    def test_execute_scripts_wraps_chunk_index_on_failure(
        self, tmp_path: Path,
    ) -> None:
        """Chunk failures should identify which raw-REPL script failed."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OK\x04\x04>",
                b"OK\x04\x04>",
                b"OK\x04Traceback: boom\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        with pytest.raises(
            CircuitpythonTransportError,
            match="chunk 2/2 failed",
        ):
            transport.execute_scripts([
                "print('chunk one')",
                "print('chunk two')",
            ])

        transport.disconnect()


class TestMemoryProbe:
    """Tests for free-memory probing and script budgeting."""

    def test_probe_free_memory_returns_integer(self) -> None:
        """probe_free_memory() should parse the board's gc.mem_free output."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OK32768\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        assert transport.probe_free_memory() == 32768

        transport.disconnect()

    def test_probe_free_memory_raises_on_non_integer_output(self) -> None:
        """probe_free_memory() should reject unexpected probe output."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OKnot-a-number\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        with pytest.raises(
            CircuitpythonTransportError,
            match="free-memory probe returned unexpected output",
        ):
            transport.probe_free_memory()

        transport.disconnect()

    def test_inline_script_budget_uses_half_the_live_heap(self) -> None:
        """inline_script_budget_bytes() should scale from live free RAM."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OK65536\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        assert transport.inline_script_budget_bytes() == 32768

        transport.disconnect()


class TestProbeImplementation:
    """Tests for CircuitpythonTransport.probe_implementation."""

    def test_parses_probe_marker_from_raw_repl_response(self) -> None:
        """A well-formed __CHU_IMPL__ line in raw REPL output is parsed."""
        from chumicro_deploy import DeviceImplementation

        marker_line = (
            "__CHU_IMPL__:circuitpython|10.1.4"
            "|Raspberry Pi Pico W with rp2040"
        )
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                b"OK" + marker_line.encode("utf-8") + b"\n\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        result = transport.probe_implementation()

        assert result == DeviceImplementation(
            name="circuitpython",
            version="10.1.4",
            machine="Raspberry Pi Pico W with rp2040",
        )

        transport.disconnect()

    def test_probe_failure_returns_none(self) -> None:
        """A malformed raw-REPL response yields None, never a raise."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                # Missing "OK" prefix.  _send_repl_command will raise,
                # and probe must swallow it.
                b"nope\x04\x04>",
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        assert transport.probe_implementation() is None

        transport.disconnect()


class TestSoftReset:
    """Tests for CircuitpythonTransport.soft_reset."""

    def test_soft_reset_exits_raw_repl_reboots_and_re_enters(self) -> None:
        """soft_reset() should exit raw REPL, reboot, then re-enter."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                _RAW_REPL_PROMPT,   # re-enter after soft reset
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        port.writes.clear()

        transport.soft_reset()

        from chumicro_deploy.circuitpython_transport import _CTRL_B
        # Should have: Ctrl-B (exit raw), Ctrl-D (reboot),
        # then Ctrl-C×2 + Ctrl-A (re-enter raw REPL).
        assert _CTRL_B in port.writes
        assert _CTRL_D in port.writes
        assert _CTRL_A in port.writes

    def test_soft_reset_raises_without_connect(self) -> None:
        """soft_reset() without a connected port should raise."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )

        with pytest.raises(
            CircuitpythonTransportError,
            match="Cannot soft_reset",
        ):
            transport.soft_reset()


class TestFlushBeforeBoardReset:
    """Tests for the flash-mode volume flush that precedes board resets.

    A reset landing while macOS still holds dirty FAT metadata can
    tear directory entries into an EINVAL state, so every reset path
    (soft reset, filesystem wipe, bootloader reset) must drain the
    host cache first.
    """

    @staticmethod
    def _record_flush_calls(
        monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, object]],
    ) -> None:
        """Replace ``flash_drive.flush_volume`` with an event recorder."""

        def recording_flush(
            drive_path: Path,
            *,
            sleep: object,
            settle_delay: float = 0.0,
        ) -> None:
            events.append(("flush", drive_path))

        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.flush_volume", recording_flush,
        )

    @staticmethod
    def _record_port_writes(
        port: FakeSerialPort, events: list[tuple[str, object]],
    ) -> None:
        """Wrap *port*'s write so every wire write lands in *events*."""
        original_write = port.write

        def recording_write(data: bytes) -> int | None:
            events.append(("write", data))
            return original_write(data)

        port.write = recording_write  # type: ignore[method-assign]

    def test_soft_reset_flushes_flash_volume_before_ctrl_d(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Flash-mode soft_reset flushes the CIRCUITPY volume, then
        sends the Ctrl-D that reboots the board.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        events: list[tuple[str, object]] = []
        self._record_flush_calls(monkeypatch, events)

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                _RAW_REPL_PROMPT,   # re-enter after soft reset
            ],
        )
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        self._record_port_writes(port, events)

        transport.soft_reset()

        assert ("flush", drive) in events
        flush_index = events.index(("flush", drive))
        ctrl_d_index = events.index(("write", _CTRL_D))
        assert flush_index < ctrl_d_index

    def test_soft_reset_ram_mode_does_not_flush(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RAM mode never writes to the drive, so its soft reset must
        not scan or flush volumes.
        """
        events: list[tuple[str, object]] = []
        self._record_flush_calls(monkeypatch, events)

        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, _RAW_REPL_PROMPT],
        )
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.connect()

        transport.soft_reset()

        assert events == []

    def test_wipe_filesystem_flushes_before_erase_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The flush runs before ``storage.erase_filesystem()`` goes on
        the wire, so no host cache write can land mid-reformat.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        events: list[tuple[str, object]] = []
        self._record_flush_calls(monkeypatch, events)

        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_kwargs: ports.pop(0),
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        self._record_port_writes(first_port, events)

        transport.wipe_filesystem()

        flush_index = events.index(("flush", drive))
        erase_index = next(
            index
            for index, (label, payload) in enumerate(events)
            if label == "write"
            and b"storage.erase_filesystem" in payload  # type: ignore[operator]
        )
        assert flush_index < erase_index

    def test_reset_into_bootloader_flushes_flash_volume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A bootloader reset detaches USB-MSC outright, so the flush
        must precede the reset command.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        events: list[tuple[str, object]] = []
        self._record_flush_calls(monkeypatch, events)

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        self._record_port_writes(port, events)

        assert transport.reset_into_bootloader() is True

        flush_index = events.index(("flush", drive))
        reset_index = next(
            index
            for index, (label, payload) in enumerate(events)
            if label == "write"
            and b"microcontroller.reset" in payload  # type: ignore[operator]
        )
        assert flush_index < reset_index


class TestDisconnect:
    """Tests for CircuitpythonTransport.disconnect."""

    def test_disconnect_closes_port(self) -> None:
        """disconnect() should close the serial port."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.disconnect()

        assert port.closed
        assert transport._port is None

    def test_disconnect_clears_staged_sources(
        self, tmp_path: Path,
    ) -> None:
        """disconnect() should clear staged data."""
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)
        assert transport.staged_sources is not None

        transport.disconnect()

        assert transport.staged_sources is None

    def test_disconnect_without_connect_is_safe(self) -> None:
        """disconnect() should not raise when connect() was never called."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )
        transport.disconnect()  # Should not raise.

    def test_disconnect_twice_is_safe(self) -> None:
        """Calling disconnect() twice should not raise."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        transport.disconnect()
        transport.disconnect()  # Should not raise.


class TestParseRawReplResponse:
    """Tests for the static response parser."""

    def test_extracts_stdout(self) -> None:
        """Parser should extract stdout from valid response."""
        response = b"OKhello world\x04\x04>"
        result = CircuitpythonTransport._parse_raw_repl_response(response)
        assert result == "hello world"

    def test_empty_stdout(self) -> None:
        """Parser should return empty string for empty stdout."""
        response = b"OK\x04\x04>"
        result = CircuitpythonTransport._parse_raw_repl_response(response)
        assert result == ""

    def test_multiline_stdout(self) -> None:
        """Parser should preserve newlines in stdout."""
        response = b"OKline1\nline2\nline3\n\x04\x04>"
        result = CircuitpythonTransport._parse_raw_repl_response(response)
        assert result == "line1\nline2\nline3\n"

    def test_raises_on_missing_ok(self) -> None:
        """Parser should raise when OK prefix is missing."""
        response = b"garbage\x04\x04>"
        with pytest.raises(
            CircuitpythonTransportError,
            match="Raw REPL did not acknowledge",
        ):
            CircuitpythonTransport._parse_raw_repl_response(response)

    def test_raises_on_stderr(self) -> None:
        """Parser should raise when stderr is non-empty."""
        response = b"OK\x04Traceback: error\x04>"
        with pytest.raises(
            CircuitpythonTransportError,
            match="CircuitPython reported an error",
        ):
            CircuitpythonTransport._parse_raw_repl_response(response)

    def test_raises_on_missing_markers(self) -> None:
        """Parser should raise on malformed response."""
        response = b"OKno markers"
        with pytest.raises(
            CircuitpythonTransportError,
            match="missing.*markers",
        ):
            CircuitpythonTransport._parse_raw_repl_response(response)


class TestFlashMode:
    """Tests for CircuitpythonTransport in flash mode."""

    def _make_flash_transport(
        self,
        port: FakeSerialPort,
        circuitpy_drive_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> CircuitpythonTransport:
        """Create a flash-mode transport with a fake serial port.

        ``circuitpy_drive_path`` is plumbed into the transport via the
        ``drive_scanner=`` constructor kwarg since the transport no
        longer accepts a pinned drive path.  Drive resolution always
        goes through candidates + verify.  Also plants a
        ``boot_out.txt`` and patches ``probe_implementation`` so
        ``_verify_drive_for_board``'s cheap path fires without
        consuming a probe response from the fake serial port.
        """
        pinned = Path(circuitpy_drive_path)
        if pinned.is_dir():
            _plant_verifiable_circuitpy(pinned, monkeypatch)
        return CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [pinned],
        )

    def test_flash_mode_stores_mode(self) -> None:
        """Flash transport should record the mode."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )
        assert transport.mode == "flash"

    def test_flash_stage_raises_when_no_drive_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should raise when drive is not found."""
        # Ensure auto-detection finds nothing.
        # Sequence: connect (prompt), stage's _enter_raw_repl (prompt),
        # stage's autoreload-off (OK).  Stage raises before any further
        # REPL traffic, and disconnect's _enter_raw_repl finds an empty
        # response and bails silently in its own try/except.  That's the
        # established contract for "drive yanked between connect and
        # stage" scenarios.
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [],
        )
        transport.connect()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        with pytest.raises(
            CircuitpythonTransportError,
            match="CIRCUITPY drive not found",
        ):
            transport.stage([source_dir], [], harness_dir)

        transport.disconnect()

    def test_flash_stage_requires_existing_drive(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should raise when drive path doesn't exist."""
        # Sequence: connect (prompt), stage's _enter_raw_repl (prompt),
        # stage's autoreload-off (OK).  Stage raises before any further
        # REPL traffic, and disconnect's _enter_raw_repl finds an empty
        # response and bails silently in its own try/except.  That's the
        # established contract for "drive yanked between connect and
        # stage" scenarios.
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(
            port, str(tmp_path / "NO_DRIVE"), monkeypatch,
        )
        transport.connect()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        with pytest.raises(
            CircuitpythonTransportError,
            match="CIRCUITPY drive not mounted",
        ):
            transport.stage([source_dir], [], harness_dir)

        transport.disconnect()

    def test_flash_stage_raises_when_rsync_fails_writability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() surfaces a writability failure via the rsync error path.

        Pre-wedge-cleanup, ``_resolve_circuitpy_drive`` wrote a
        ``.chu-probe`` marker to detect stale/unwritable mounts up
        front.  That extra on-drive write was a wedge-risk vector
        on macOS FSKit (parallel direct writes during a live rsync
        could hang in uninterruptible kernel I/O) and was dropped.
        rsync's own write failure is now the writability signal.
        Its stderr surfaces the OS error and ``flash_drive.rsync``
        wraps it as :class:`FlashDriveError`.

        Simulated by mocking ``subprocess.run`` to raise
        ``CalledProcessError`` with a permission-denied stderr (the
        signature of a stale Finder-eject mount).
        """
        import os
        import subprocess as _subprocess

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        # Sequence: connect (prompt), stage's _enter_raw_repl (prompt),
        # stage's autoreload-off (OK).  Stage raises before any further
        # REPL traffic, and disconnect's _enter_raw_repl finds an empty
        # response and bails silently in its own try/except.  That's the
        # established contract for "drive yanked between connect and
        # stage" scenarios.
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )
        transport = self._make_flash_transport(port, str(drive), monkeypatch)
        transport.connect()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Mock rsync to fail with permission denied.  Pass other
        # subprocess calls (xattr, mdutil, dot_clean, sync) through
        # cleanly so they don't masquerade as the failing call.
        original_run = _subprocess.run

        def fake_run(command, **kwargs):
            if command and str(command[0]) == "rsync":
                raise _subprocess.CalledProcessError(
                    1, "rsync", stderr="rsync: permission denied",
                )
            return original_run(command, **kwargs)
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.subprocess.run", fake_run,
        )

        original_mode = drive.stat().st_mode
        try:
            with pytest.raises(
                CircuitpythonTransportError,
                match="rsync failed",
            ):
                transport.stage([source_dir], [], harness_dir)
        finally:
            os.chmod(drive, original_mode)

        transport.disconnect()

    def test_flash_stage_copies_packages_to_lib(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should copy packages to lib/ on drive."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "ticks.py").write_text("def ticks_ms(): pass")

        harness_dir = tmp_path / "harness"
        harness_package = harness_dir / "chumicro_test_harness"
        harness_package.mkdir(parents=True)
        (harness_package / "__init__.py").write_text("# harness")
        (harness_package / "runner.py").write_text("def run_module(): pass")

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        # Check that packages were copied to lib/.
        lib_dir = drive_path / "lib"
        assert lib_dir.is_dir()
        assert (lib_dir / "chumicro_timing" / "__init__.py").exists()
        assert (lib_dir / "chumicro_timing" / "ticks.py").exists()
        assert (lib_dir / "chumicro_test_harness" / "__init__.py").exists()
        assert (lib_dir / "chumicro_test_harness" / "runner.py").exists()

        transport.disconnect()

    def test_flash_stage_copies_test_files_to_root(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should copy test files to drive root."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [test_file], harness_dir)

        assert (drive_path / "test_example.py").exists()
        assert (drive_path / "test_example.py").read_text() == "def test_ok(): pass"

        transport.disconnect()

    def test_functional_stage_is_unified_clean_slate_with_named_fork(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Functional stage() is the same clean-slate path, fork only named.

        Single-staging-path rule: the functional-test stage issues the
        *identical* rsync invocation as a production clean deploy
        (``--delete`` + ``DEVICE_KEEP_SET``, no per-context ``code.py``
        carve-out), so a stale board ``code.py`` / ``settings.toml`` is
        reconciled away while the keep set survives.  The only
        sanctioned divergence is the recorded :class:`PostStageStep`.
        """
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()
        # Board carries leftovers from a prior project deploy.
        (drive_path / "code.py").write_text("# stale project entrypoint")
        (drive_path / "settings.toml").write_text("WIFI_SSID = 'board'\n")

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        import subprocess as _subprocess
        original_run = _subprocess.run
        rsync_argv: list[list[str]] = []

        def recording_run(command, **kwargs):
            if command and str(command[0]) == "rsync":
                rsync_argv.append([str(part) for part in command])
            return original_run(command, **kwargs)

        monkeypatch.setattr(_subprocess, "run", recording_run)

        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )
        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [test_file], harness_dir)

        # Bytes-on-device path: stale entrypoint + competing wifi
        # authority reconciled away, keep set survives, payload landed.
        assert not (drive_path / "code.py").exists()
        assert not (drive_path / "settings.toml").exists()
        assert (drive_path / "boot_out.txt").exists()  # DEVICE_KEEP_SET
        assert (drive_path / "test_example.py").exists()

        # The rsync invocation is the clean one, with no per-context
        # code.py exclude.
        assert rsync_argv, "rsync was not invoked"
        argv = rsync_argv[0]
        assert "--delete" in argv
        for keep in ("boot.py", "boot_out.txt", "_chu_kv.msgpack"):
            assert f"--exclude={keep}" in argv
        assert "--exclude=code.py" not in argv
        assert "--exclude=settings.toml" not in argv

        # The one sanctioned per-context divergence, named.
        assert transport._post_stage_step is PostStageStep.HARNESS_EXEC_OVER_REPL

        transport.disconnect()

    def test_flash_stage_fails_loud_on_torn_directory_entries(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A torn FAT entry found by the post-sync stat sweep fails the
        stage with one actionable error naming the path and the
        reset-board recovery command, before any reset can land.
        """
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.scan_for_torn_directory_entries",
            lambda _drive_path: ["lib/chumicro_config/section.py"],
        )

        # Sequence: connect (prompt), stage's _enter_raw_repl (prompt),
        # autoreload-off (OK).  The corruption error fires before the
        # FAT cache refresh, so no further REPL traffic follows.
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )
        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()

        with pytest.raises(
            CircuitpythonTransportError,
            match="FAT directory entries",
        ) as exc_info:
            transport.stage([source_dir], [], harness_dir)
        message = str(exc_info.value)
        assert "lib/chumicro_config/section.py" in message
        assert "reset-board" in message

        transport.disconnect()

    def test_flash_stage_sends_autoreload_disable(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should send autoreload disable via REPL."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        port.writes.clear()

        transport.stage([source_dir], [], harness_dir)

        # Should have sent autoreload disable command.
        written_data = b"".join(port.writes)
        assert b"autoreload" in written_data
        assert b"False" in written_data

        transport.disconnect()

    def test_flash_stage_disables_autoreload_before_any_drive_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Order regression: the autoreload-off REPL command MUST land on
        the wire BEFORE rsync (or any other host-side write to the
        CIRCUITPY drive) starts.

        With autoreload ON (the default), the board's filesystem
        watcher fires a soft-reboot on the first file change.  Each
        soft-reboot re-enumerates USB-CDC.  Multiple re-enumerations
        in rapid succession can put the kernel-side write into D-state,
        the wedged-rsync failure mode (rsync subprocess in D-state,
        ``kill -9`` ineffective, only a board reboot clears it).

        Post-cleanup: there is now only ONE host-side drive write,
        the rsync itself.  Drive prep (sentinel plants) goes into
        the local staging tree.  The ``.chu-probe`` marker write was
        dropped from ``_resolve_circuitpy_drive`` in the default path.
        This test snapshots the order of:

        1. Wire write of the autoreload command
        2. Subprocess invocation of ``rsync``

        and asserts (1) precedes (2).
        """
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        events: list[tuple[int, str]] = []

        def event(label: str) -> None:
            events.append((len(events), label))

        # Sequence: connect prompt; _push_staging_to_drive
        # (enter_raw_repl + autoreload_off + FAT cache refresh);
        # disconnect (enter_raw_repl, then Ctrl-B — no further reads).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        # Wrap FakeSerialPort.write to record when "autoreload" + "False"
        # cross the wire (the autoreload-off command).
        original_write = port.write

        def recording_write(data: bytes) -> int:
            if b"autoreload" in data and b"False" in data:
                event("wire: autoreload off")
            return original_write(data)
        port.write = recording_write  # type: ignore[assignment]

        # Wrap subprocess.run to record when rsync is invoked.  Other
        # subprocess calls (xattr, dot_clean, sync) come AFTER rsync,
        # so tracking rsync alone is sufficient for the order assertion.
        import subprocess as _subprocess
        original_run = _subprocess.run

        def recording_run(command, **kwargs):
            if command and str(command[0]) == "rsync":
                event("subprocess: rsync invoked")
            return original_run(command, **kwargs)
        monkeypatch.setattr(_subprocess, "run", recording_run)

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [], harness_dir)
        transport.disconnect()

        labels_in_order = [label for _ordinal, label in events]
        autoreload_index = labels_in_order.index("wire: autoreload off")
        rsync_index = labels_in_order.index("subprocess: rsync invoked")
        assert autoreload_index < rsync_index, (
            "regression: rsync runs BEFORE autoreload off; "
            f"order was {labels_in_order}.  The board's autoreload "
            "watcher will fire on the first rsync write and "
            "re-enumerate USB-CDC, leaving subsequent writes at risk "
            "of D-state."
        )

    def test_flash_disconnect_does_not_touch_autoreload(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """disconnect() in flash mode emits Ctrl-B only, no Ctrl-C, no autoreload flip.

        Ctrl-C would interrupt the ``code.py`` that ``deploy_files``
        leaves running.  An autoreload-on flip can layer a second
        soft-reboot on top of one already in flight and wedge the
        ESP32-S2 USB-CDC firmware.
        """
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(
            port, str(tmp_path / "CIRCUITPY"), monkeypatch,
        )
        transport.connect()
        port.writes.clear()

        transport.disconnect()

        from chumicro_deploy.circuitpython_transport import _CTRL_B
        written_data = b"".join(port.writes)
        assert _CTRL_B in port.writes
        assert _CTRL_C not in port.writes
        assert _CTRL_A not in port.writes
        assert b"autoreload" not in written_data

    def test_ram_disconnect_does_not_send_autoreload(self) -> None:
        """disconnect() in ram mode emits Ctrl-B only, same shape as flash.

        ram mode never disables autoreload, so there is nothing to
        restore.  The parity is asserted explicitly so the two paths
        cannot drift.
        """
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        port.writes.clear()

        transport.disconnect()

        from chumicro_deploy.circuitpython_transport import _CTRL_B
        written_data = b"".join(port.writes)
        assert b"autoreload" not in written_data
        assert _CTRL_B in port.writes
        assert _CTRL_D not in port.writes
        assert _CTRL_C not in port.writes

    def test_flash_stage_is_idempotent_across_calls(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Repeated stage() calls should produce the same drive state."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text('marker = "init"')

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        test_file_one = tmp_path / "test_one.py"
        test_file_one.write_text("def test_one(): pass")
        test_file_two = tmp_path / "test_two.py"
        test_file_two.write_text("def test_two(): pass")

        # Responses: connect (prompt) + 2 stages (each: enter_raw_repl
        # + autoreload off + FAT cache refresh) + disconnect
        # (enter_raw_repl).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()

        # First stage: libs + test_one.
        transport.stage([source_dir], [test_file_one], harness_dir)
        assert (drive_path / "lib" / "chumicro_timing" / "__init__.py").exists()
        assert (drive_path / "test_one.py").exists()

        # Second stage with test_two.  rsync replaces root test files
        # and keeps libs intact (checksum match = no rewrite).
        transport.stage([source_dir], [test_file_two], harness_dir)
        assert (drive_path / "test_two.py").exists()
        # test_one should be gone (--delete removes stale files).
        assert not (drive_path / "test_one.py").exists()
        # Library content is unchanged.
        lib_init = drive_path / "lib" / "chumicro_timing" / "__init__.py"
        assert lib_init.read_text() == 'marker = "init"'

        transport.disconnect()

    def test_flash_stage_excludes_pycache(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should not copy __pycache__ to the drive."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "ticks.py").write_text("def ticks_ms(): pass")
        # Create a __pycache__ directory with .pyc files.
        pycache_dir = package_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "ticks.cpython-314.pyc").write_bytes(b"\x00")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        lib_dir = drive_path / "lib"
        assert (lib_dir / "chumicro_timing" / "__init__.py").exists()
        assert (lib_dir / "chumicro_timing" / "ticks.py").exists()
        assert not (lib_dir / "chumicro_timing" / "__pycache__").exists()

        transport.disconnect()

    def test_flash_stage_overwrites_existing_package(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() should overwrite existing files and remove stale ones."""
        drive_path = tmp_path / "CIRCUITPY"
        lib_dir = drive_path / "lib" / "chumicro_timing"
        lib_dir.mkdir(parents=True)
        (lib_dir / "__init__.py").write_text("# old")
        (lib_dir / "stale_file.py").write_text("# leftover from old version")

        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text('marker = "new"')

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path), monkeypatch)
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        # Existing files are overwritten with new content.
        assert (lib_dir / "__init__.py").read_text() == 'marker = "new"'
        # Stale files are removed by rsync --delete.
        assert not (lib_dir / "stale_file.py").exists()

        transport.disconnect()
class TestSendReplCommand:
    """Tests for _send_repl_command."""

    def test_send_repl_command_returns_stdout(self) -> None:
        """_send_repl_command should return the stdout portion."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                b"OKhello\x04\x04>",  # command response
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()

        result = transport._send_repl_command("print('hello')")
        assert result == "hello"

        transport.disconnect()

    def test_send_repl_command_raises_without_connect(self) -> None:
        """_send_repl_command should raise when not connected."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )

        with pytest.raises(
            CircuitpythonTransportError,
            match="connect",
        ):
            transport._send_repl_command("print('hello')")


class TestCircuitpyVolumeCandidates:
    """Tests for _circuitpy_volume_candidates auto-detection.

    The candidates helper is what `_resolve_circuitpy_drive` walks at
    deploy time.  It globs every mounted ``CIRCUITPY*`` directory on
    each base path so the verify layer can pick the UID-matching one
    on multi-board hosts.  These tests cover the base-path logic
    (macOS ``/Volumes`` and Linux ``/media/<user>`` / ``/run/media/<user>``)
    independent of the per-board UID match.
    """

    def test_returns_empty_when_no_drive_found(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No mounted CIRCUITPY drive -> empty list."""
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_base_paths",
            lambda: [],
        )
        assert _circuitpy_volume_candidates() == []

    def test_finds_macos_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A CIRCUITPY volume under a base path is returned."""
        fake_volumes = tmp_path / "Volumes"
        fake_drive = fake_volumes / "CIRCUITPY"
        fake_drive.mkdir(parents=True)
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_base_paths",
            lambda: [fake_volumes],
        )
        assert _circuitpy_volume_candidates() == [fake_drive]

    def test_finds_linux_media_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A CIRCUITPY volume under /media/<user> style base is returned."""
        media_user = tmp_path / "media" / "testuser"
        fake_drive = media_user / "CIRCUITPY"
        fake_drive.mkdir(parents=True)
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_base_paths",
            lambda: [media_user],
        )
        assert _circuitpy_volume_candidates() == [fake_drive]

    def test_globs_all_circuitpy_siblings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every ``CIRCUITPY*`` directory in a base path is returned, sorted."""
        volumes = tmp_path / "Volumes"
        first = volumes / "CIRCUITPY"
        second = volumes / "CIRCUITPY 1"
        third = volumes / "CIRCUITPY 2"
        for drive in (first, second, third):
            drive.mkdir(parents=True)
        # Out-of-scope siblings must be ignored.
        (volumes / "OTHER").mkdir()
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_base_paths",
            lambda: [volumes],
        )
        assert _circuitpy_volume_candidates() == [first, second, third]

    def test_skips_missing_base_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Base paths that don't exist on disk are silently skipped."""
        present = tmp_path / "present"
        present.mkdir()
        (present / "CIRCUITPY").mkdir()
        missing = tmp_path / "missing"
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_base_paths",
            lambda: [missing, present],
        )
        assert _circuitpy_volume_candidates() == [present / "CIRCUITPY"]


class TestCircuitpyBasePaths:
    """Tests for _circuitpy_base_paths username-resolution behavior.

    Linux ``/media/<user>`` and ``/run/media/<user>`` mount bases need
    a real username.  Slim containers without ``$USER`` exported still
    have to fall back through ``getpass.getuser`` to the OS password
    database, and degrade gracefully to ``/Volumes``-only when even
    that's unavailable rather than producing malformed ``/media//`` paths.
    """

    def test_falls_back_to_getpass_when_user_env_unset(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy.circuitpy_drive import (
            _circuitpy_base_paths,
        )

        monkeypatch.delenv("USER", raising=False)
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive.getpass.getuser",
            lambda: "fallback_user",
        )
        bases = _circuitpy_base_paths()
        assert Path("/media/fallback_user") in bases
        assert Path("/media/") not in bases
        assert Path("/run/media/fallback_user") in bases

    def test_skips_linux_paths_when_username_unresolvable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy.circuitpy_drive import (
            _circuitpy_base_paths,
        )

        monkeypatch.delenv("USER", raising=False)

        def boom() -> str:
            raise KeyError("no passwd entry")

        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive.getpass.getuser",
            boom,
        )
        bases = _circuitpy_base_paths()
        # Linux media bases require a username, so falling back to /Volumes
        # alone keeps us out of /media//CIRCUITPY territory.
        assert bases == [Path("/Volumes")]

    def test_flash_stage_auto_detects_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should auto-detect the drive path."""
        fake_drive = tmp_path / "CIRCUITPY"
        fake_drive.mkdir()

        # Make _circuitpy_volume_candidates return our fake path.
        _plant_verifiable_circuitpy(fake_drive, monkeypatch)

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect (prompt), _push_staging_to_drive's
        # _enter_raw_repl (prompt) + autoreload disable (OK), FAT
        # cache refresh after rsync (OK), disconnect raw_repl (prompt).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                _RAW_REPL_PROMPT, _OK_RESPONSE, _OK_RESPONSE,
                _RAW_REPL_PROMPT,
            ],
        )

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=lambda: [fake_drive],
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        # Should have used the auto-detected path, lib/ created there.
        assert (fake_drive / "lib").is_dir()

        transport.disconnect()


class TestResetIntoBootloader:
    """Tests for CircuitpythonTransport.reset_into_bootloader."""

    def test_sends_microcontroller_reset_script(self) -> None:
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **_kwargs: port,
            time=FakeTime(),
        )
        transport.connect()
        assert transport.reset_into_bootloader() is True
        combined_writes = b"".join(port.writes).decode("utf-8", errors="replace")
        assert "microcontroller.RunMode.BOOTLOADER" in combined_writes
        assert "microcontroller.reset()" in combined_writes

    def test_returns_false_when_port_is_none(self) -> None:
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **_kwargs: FakeSerialPort(),
            time=FakeTime(),
        )
        # connect() was never called, so _port stays None.
        assert transport.reset_into_bootloader() is False

    def test_send_exception_swallowed_returns_true(self) -> None:
        # No _OK_RESPONSE supplied: _send_repl_command will raise when
        # it fails to parse.  That's the expected success signal (board
        # resets mid-command).
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **_kwargs: port,
            time=FakeTime(),
        )
        transport.connect()
        assert transport.reset_into_bootloader() is True

    def test_disconnect_after_reset_is_silent(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """After reset_into_bootloader, disconnect() skips the restore
        dance and emits no warnings.  The USB link is gone on purpose.
        """
        # Read sequence: connect (prompt) + reset OK + (no more reads
        # because disconnect now skips _enter_raw_repl + autoreload).
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",  # disconnect path is mode-uniform now
            serial_port_factory=lambda **_kwargs: port,
            time=FakeTime(),
        )
        transport.connect()
        assert transport.reset_into_bootloader() is True

        # Drain whatever the connect + reset produced so we can
        # assert disconnect itself stays silent.
        capsys.readouterr()

        transport.disconnect()

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
        assert "WARNING" not in captured.err
        assert port.closed
        # reset_into_bootloader nulled the port itself.  Disconnect
        # had nothing left to restore or close and the transport is
        # reusable via a fresh connect() once the board is back.
        assert transport._port is None


class TestDeployFiles:
    """Tests for CircuitpythonTransport.deploy_files."""

    def _connect(
        self,
        *,
        mode: str = "flash",
        drive_path: str | None = None,
        extra_responses: list[bytes] | None = None,
        monkeypatch: pytest.MonkeyPatch | None = None,
    ) -> tuple[CircuitpythonTransport, FakeSerialPort]:
        # Responses for: connect (prompt) + re-enter raw REPL (prompt) +
        # autoreload-off command (OK) + entrypoint exec (OK with output).
        # Tests supply the extra OK responses for additional commands.
        reads = [_RAW_REPL_PROMPT]
        if extra_responses:
            reads.extend(extra_responses)
        port = FakeSerialPort(read_responses=reads)

        drive_scanner = None
        if drive_path is not None and monkeypatch is not None:
            pinned = Path(drive_path)
            drive_scanner = lambda: [pinned]  # noqa: E731
            if pinned.is_dir():
                _plant_verifiable_circuitpy(pinned, monkeypatch)

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode=mode,
            serial_port_factory=port,
            time=FakeTime(),
            drive_scanner=drive_scanner,
        )
        transport.connect()
        return transport, port

    def test_ram_mode_deploys_inline(self, tmp_path: Path) -> None:
        """RAM mode inlines the files via raw REPL and execs __main__.

        Read sequence (FakeSerialPort returns these in order):

        - ``_RAW_REPL_PROMPT`` for the initial ``connect()``.
        - ``OK<free_memory>\\x04\\x04>`` for
          ``inline_script_budget_bytes`` -> ``probe_free_memory``.
        - One OK per bootstrap chunk (4 chunks: helpers, stubs,
          populations, final).  The final chunk returns the
          entrypoint's stdout.
        - One OK per gc.collect interstitial between chunks (3).
        """
        probe_response = b"OK65536\r\n\x04\x04>"
        final_chunk_response = b"OKinline-main\r\n\x04\x04>"
        # execute() loop: chunk, (gc), chunk, (gc), chunk, (gc), chunk.
        # The last chunk has no trailing gc.collect.
        chunk_and_gc_pairs = [
            _OK_RESPONSE,  # chunk 1 (helpers)
            _OK_RESPONSE,  # gc.collect after chunk 1
            _OK_RESPONSE,  # chunk 2 (stub registrations)
            _OK_RESPONSE,  # gc.collect after chunk 2
            _OK_RESPONSE,  # chunk 3 (populations)
            _OK_RESPONSE,  # gc.collect after chunk 3
            final_chunk_response,  # chunk 4 (final entrypoint exec)
        ]
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,
                probe_response,
                *chunk_and_gc_pairs,
            ],
        )
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            serial_port_factory=lambda **_kwargs: port,
            time=FakeTime(),
        )
        transport.connect()

        staged: list[str] = []
        lines: list[str] = []
        output = transport.deploy_files(
            {
                "/code.py": b"print('inline-main')\n",
                "/lib/helper.py": b"CONSTANT = 42\n",
            },
            "/code.py",
            on_file_staged=staged.append,
            on_execute_line=lines.append,
        )

        assert "inline-main" in output
        # Sorted order: /code.py before /lib/helper.py.
        assert staged == ["/code.py", "/lib/helper.py"]
        assert lines == list(output.splitlines())
        # The raw REPL traffic should include a populate-block for
        # the helper module and an exec() of the entrypoint.
        combined_writes = b"".join(port.writes).decode("utf-8", errors="replace")
        assert "_register_stub('helper')" in combined_writes
        assert "_populate_module" in combined_writes
        assert "'__main__'" in combined_writes

    def test_ram_mode_requires_entrypoint_in_files(
        self, tmp_path: Path,
    ) -> None:
        transport, _ = self._connect(mode="ram", drive_path=str(tmp_path))
        with pytest.raises(
            CircuitpythonTransportError,
            match="missing from files",
        ):
            transport.deploy_files(
                {"/code.py": b"pass"}, "/boot.py",
            )

    @staticmethod
    def _boot_output(user_text: bytes) -> bytes:
        """Build a canned soft-boot serial capture ending in the done marker."""
        return (
            b"soft reboot\r\n\r\n"
            b"Adafruit CircuitPython X.Y.Z on YYYY-MM-DD; TestBoard with rp2040\r\n"
            b"Board ID:test_board\r\n\r\n"
            b"code.py output:\r\n"
            + user_text
            + b"\r\nCode done running.\r\n\r\nPress any key to enter the REPL.\r\n"
        )

    @staticmethod
    def _stat_response(size: int) -> bytes:
        """Canned raw-REPL response for the board-side ``os.stat`` poll."""
        return _repl_response(stdout=f"{size}\r\n".encode("ascii"))

    def test_writes_files_to_drive_and_execs_entrypoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,         # _enter_raw_repl reentry (pre-writes)
            _OK_RESPONSE,             # autoreload-off ack
            self._stat_response(len(b"print('hi')")),  # board sees entrypoint
            self._boot_output(b"hello"),  # soft-reboot output capture
            _RAW_REPL_PROMPT,         # _enter_raw_repl after soft-reboot
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        output = transport.deploy_files(
            {"/code.py": b"print('hi')", "/lib/util.py": b"X = 1"},
            "/code.py",
        )
        assert "hello" in output
        assert (drive / "code.py").read_bytes() == b"print('hi')"
        assert (drive / "lib" / "util.py").read_bytes() == b"X = 1"

    def test_autoreload_disabled_before_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
            self._boot_output(b""),
            _RAW_REPL_PROMPT,
        ]
        transport, port = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        transport.deploy_files({"/code.py": b"pass"}, "/code.py")
        combined_writes = b"".join(port.writes).decode("utf-8", errors="replace")
        assert "supervisor.runtime.autoreload = False" in combined_writes

    def test_flushes_volume_again_directly_before_soft_reboot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The last three steps before the reboot are flush, Ctrl-B,
        Ctrl-D, in that order.

        The staging push flushes once, but the post-rsync verification
        re-reads the volume afterwards, so a second flush must be the
        final host-side drive operation before the Ctrl-D lands.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        events: list[tuple[str, object]] = []

        def recording_flush(
            drive_path: Path,
            *,
            sleep: object,
            settle_delay: float = 0.0,
        ) -> None:
            events.append(("flush", drive_path))

        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.flush_volume", recording_flush,
        )

        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
            self._boot_output(b""),
            _RAW_REPL_PROMPT,
        ]
        transport, port = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        original_write = port.write

        def recording_write(data: bytes) -> int | None:
            events.append(("write", data))
            return original_write(data)

        port.write = recording_write  # type: ignore[method-assign]

        transport.deploy_files({"/code.py": b"pass"}, "/code.py")

        from chumicro_deploy.circuitpython_transport import _CTRL_B
        flush_events = [event for event in events if event[0] == "flush"]
        assert len(flush_events) == 2  # staging push + pre-reboot barrier
        assert events[-3:] == [
            ("flush", drive),
            ("write", _CTRL_B),
            ("write", _CTRL_D),
        ]

    def test_on_file_staged_invoked_per_file_sorted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
            self._boot_output(b""),
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        staged: list[str] = []
        transport.deploy_files(
            {"/lib/util.py": b"X = 1", "/code.py": b"pass"},
            "/code.py",
            on_file_staged=staged.append,
        )
        assert staged == ["/code.py", "/lib/util.py"]

    def test_on_execute_line_emits_per_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
            self._boot_output(b"one\r\ntwo\r\nthree"),
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        lines: list[str] = []
        transport.deploy_files(
            {"/code.py": b"pass"}, "/code.py", on_execute_line=lines.append
        )
        assert lines == ["one", "two", "three"]

    def test_missing_entrypoint_raises(self, tmp_path: Path) -> None:
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        transport, _ = self._connect(drive_path=str(drive))
        with pytest.raises(CircuitpythonTransportError, match="entrypoint"):
            transport.deploy_files({"/code.py": b"pass"}, "/missing.py")

    def test_missing_drive_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [],
        )
        # deploy_files in flash mode now does:
        #   _enter_raw_repl   -> consumes a prompt
        #   _disable_autoreload_before_drive_writes -> consumes an OK
        #   _resolve_circuitpy_drive  -> raises (find returns None)
        transport, _ = self._connect(
            drive_path=None,
            extra_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE],
        )
        with pytest.raises(CircuitpythonTransportError, match="CIRCUITPY drive not found"):
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")

    def test_tail_seconds_zero_returns_immediately_with_empty_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``tail_seconds=0`` must short-circuit the post-Ctrl-D capture.

        Caller wants to leave the board running and not block.  The
        Ctrl-D goes out, the read loop is skipped entirely, output is
        empty.  No serial-read response needs queuing in the fake.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        output = transport.deploy_files(
            {"/code.py": b"pass"},
            "/code.py",
            tail_seconds=0.0,
        )
        assert output == ""

    def test_tail_seconds_overrides_default_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An explicit ``tail_seconds`` value reaches _read_code_py_output."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"pass")),
            self._boot_output(b"hello"),
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        captured_window: list[float | None] = []
        original_read = transport._read_code_py_output

        def spy(*, tail_seconds: float | None = None) -> str:
            captured_window.append(tail_seconds)
            return original_read(tail_seconds=tail_seconds)

        transport._read_code_py_output = spy  # type: ignore[method-assign]
        transport.deploy_files(
            {"/code.py": b"pass"},
            "/code.py",
            tail_seconds=42.0,
        )
        assert captured_window == [42.0]

    def test_post_rsync_verification_failure_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """deploy_files must raise before Ctrl-D when verify_rsync reports divergence.

        Soft-rebooting against an inconsistent FAT volume risks the
        volume going read-only, typically recoverable only by
        reformatting (`chumicro-workspace reset-board --yes`),
        since RESET alone often does not clear it.  The error
        message must name the recovery path.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport.flash_drive.verify_rsync",
            lambda *_args, **_kwargs: ["/code.py"],
        )
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        with pytest.raises(
            CircuitpythonTransportError,
            match="verification found",
        ):
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")

    def test_inline_script_budget_raises_on_low_memory(self) -> None:
        """inline_script_budget_bytes() must refuse when probe reports too little RAM."""
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, b"OK128\n\x04\x04>"],
        )
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **_kwargs: port,
            time=FakeTime(),
        )
        transport.connect()
        with pytest.raises(
            CircuitpythonTransportError, match="too little free RAM",
        ):
            transport.inline_script_budget_bytes()

    def test_warn_if_flush_produced_empty_file_skips_when_probe_absent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No warning when the probe file didn't land on the drive at all."""
        test_file = tmp_path / "t.py"
        test_file.write_bytes(b"pass")
        CircuitpythonTransport._warn_if_flush_produced_empty_file(
            tmp_path / "elsewhere", [test_file],
        )
        assert capsys.readouterr().out == ""

    def test_warn_if_flush_produced_empty_file_warns_on_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Warn when the probe landed on the drive but is empty."""
        test_file = tmp_path / "t.py"
        test_file.write_bytes(b"pass")
        (tmp_path / "t.py").write_bytes(b"pass")
        drive = tmp_path / "drive"
        drive.mkdir()
        (drive / "t.py").write_bytes(b"")
        CircuitpythonTransport._warn_if_flush_produced_empty_file(
            drive, [test_file],
        )
        assert "empty after flush" in capsys.readouterr().out

    def test_recover_without_connection_raises(self) -> None:
        """recover() must refuse to run on a transport that never connected."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            serial_port_factory=lambda **_kwargs: FakeSerialPort(),
            time=FakeTime(),
        )
        with pytest.raises(
            CircuitpythonTransportError, match="port is not open",
        ):
            transport.recover()

    def test_oserror_during_copy_is_classified_as_drive_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Eject-between-probe-and-copy should surface as drive-missing.

        The probe in :meth:`_resolve_circuitpy_drive` catches the
        common case, but the drive can disappear between the probe
        and the write loop.  Simulate by letting the probe succeed and
        raising :class:`PermissionError` on the real file write.  The
        wrapper should re-raise as
        :class:`CircuitpythonTransportError` with the
        classifier-matching "CIRCUITPY drive not found" phrase.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        # Extra responses: _enter_raw_repl prompt + autoreload-off OK.
        transport, _ = self._connect(
            drive_path=str(drive),
            extra_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE],
        )

        original_write_bytes = Path.write_bytes

        def selective_write_bytes(self: Path, data: bytes) -> int:
            if self.name == ".chu-probe":
                return original_write_bytes(self, data)
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "write_bytes", selective_write_bytes)

        with pytest.raises(
            CircuitpythonTransportError,
            match="CIRCUITPY drive not found or not writable",
        ):
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")

    def test_unconnected_raises(self, tmp_path: Path) -> None:
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=lambda **_: FakeSerialPort(),
            time=FakeTime(),
        )
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")

    def test_clean_deploy_evicts_settings_toml_keeps_keepset_and_notices(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A clean deploy removes a board settings.toml + keeps the keep set.

        End-to-end check of the unified keep set: ``settings.toml`` is
        a competing wifi authority and is evicted by ``rsync
        --delete`` (it is not in ``DEVICE_KEEP_SET``), with a one-time
        loud notice.  ``boot_out.txt`` (planted by the verifiable-drive
        helper, in the keep set) survives.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "settings.toml").write_text("WIFI_SSID = 'board-owned'\n")
        content = b"print('clean')\n"
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(content)),
            self._boot_output(b"clean"),
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        transport.deploy_files(
            {"/code.py": content}, "/code.py", clean=True,
        )
        out = capsys.readouterr().out
        assert "WARNING: removing the board's settings.toml" in out
        assert not (drive / "settings.toml").exists()  # evicted
        assert (drive / "boot_out.txt").exists()  # keep set survives
        assert (drive / "code.py").read_bytes() == content
        # Same clean-slate bytes path as the functional stage.  The only
        # sanctioned divergence is this named post-stage fork.
        assert transport._post_stage_step is PostStageStep.SOFT_REBOOT_AND_TAIL

    def test_additive_deploy_does_not_evict_or_notice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """clean=False (additive scope) leaves settings.toml + stays quiet."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "settings.toml").write_text("WIFI_SSID = 'board-owned'\n")
        content = b"print('additive')\n"
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(content)),
            self._boot_output(b"additive"),
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        transport.deploy_files({"/code.py": content}, "/code.py")
        out = capsys.readouterr().out
        assert "settings.toml" not in out
        assert (drive / "settings.toml").exists()  # additive preserves it

    def test_stale_pre_reboot_banner_is_discarded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-reboot stale output must not leak into the capture.

        Reproduces the Pi Pico W "one-cycle-delayed capture" failure
        mode.  Host opens the port, drain doesn't fully clear CP's
        USB-CDC buffer, and the buffer still holds a complete
        ``code.py output: ... Code done running.`` pair from the
        *previous* deploy.  The new ``_read_code_py_output`` sync on
        the ``soft reboot`` marker keeps the old pair out of the
        returned capture so callers see only the fresh run's output.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        stale = (
            b"code.py output:\r\n"
            b"\x1b]0;board | code.py | X.Y.Z\x1b\\"
            b"old-output\r\nTraceback (most recent call last):\r\n"
            b"  File \"code.py\", line 2, in <module>\r\n"
            b"ZeroDivisionError: division by zero\r\n"
            b"\x1b]0;board | Done | X.Y.Z\x1b\\"
            b"\r\nCode done running.\r\n\r\n"
        )
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(len(b"print('fresh')")),
            stale,                         # noise left over from last run
            self._boot_output(b"fresh-output"),  # real soft-reboot output
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        output = transport.deploy_files(
            {"/code.py": b"print('fresh')"}, "/code.py",
        )
        assert "fresh-output" in output
        assert "old-output" not in output
        assert "ZeroDivisionError" not in output

    def test_waits_for_board_to_see_new_entrypoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """USB-MSC write visibility to CP is polled, not assumed.

        On a slow controller the first ``os.stat`` can still report
        the previous file's size, so the transport retries until the
        board sees the new length, guaranteeing that the soft-reboot
        runs the file we just wrote rather than a stale cached one.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        new_contents = b"print('fresh')\n"
        stale_size = len(b"print('old-bigger-file')\n")
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            self._stat_response(stale_size),          # first poll: stale
            self._stat_response(stale_size),          # second poll: stale
            self._stat_response(len(new_contents)),   # third poll: fresh
            self._boot_output(b"fresh-output"),
            _RAW_REPL_PROMPT,
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        output = transport.deploy_files(
            {"/code.py": new_contents}, "/code.py",
        )
        assert "fresh-output" in output

    def test_raises_if_board_never_sees_new_entrypoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the board never reports the expected size, deploy fails loudly."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        new_contents = b"print('never-visible')\n"
        stale = self._stat_response(99)
        # Supply enough stale responses to exhaust the poll budget.
        extra = [
            _RAW_REPL_PROMPT,
            _OK_RESPONSE,
            *([stale] * 20),
        ]
        transport, _ = self._connect(
            drive_path=str(drive), extra_responses=extra,
            monkeypatch=monkeypatch,
        )
        with pytest.raises(
            CircuitpythonTransportError,
            match="did not see .* bytes",
        ):
            transport.deploy_files(
                {"/code.py": new_contents}, "/code.py",
            )


class TestDriveVerification:
    """Tests for the mount-order-safe drive verification path.

    macOS assigns ``/Volumes/CIRCUITPY`` by mount order, so a
    ``circuitpy_drive_path`` pinned in ``devices.yml`` can silently
    target the other board when two CP boards are plugged in at once.
    :meth:`CircuitpythonTransport._verify_drive_for_board` reads
    ``boot_out.txt`` on the configured drive, probes the connected
    board, and either confirms the match, auto-corrects to a sibling
    mount, or raises with guidance.
    """

    @staticmethod
    def _boot_out(machine: str, uid: str = "DEADBEEF") -> str:
        return (
            f"Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; {machine}\n"
            "Board ID:test_board\n"
            f"UID:{uid}\n"
            "MAC:00:00:00:00:00:00\n"
        )

    @staticmethod
    def _probe_response(machine: str, uid: str = "") -> bytes:
        marker_line = f"__CHU_IMPL__:circuitpython|10.2.0|{machine}"
        if uid:
            marker_line += f"\n__CHU_UID__:{uid}"
        else:
            marker_line += "\n__CHU_UID__:"
        return b"OK" + marker_line.encode("utf-8") + b"\n\x04\x04>"

    def _make_transport(
        self,
        *,
        drive_path: str,
        reads: list[bytes],
    ) -> tuple[CircuitpythonTransport, FakeSerialPort]:
        port = FakeSerialPort(read_responses=reads)

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=port,
            time=FakeTime(),
        )
        transport.connect()
        return transport, port

    def test_raises_when_boot_out_missing_and_probe_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No boot_out.txt + no probe response -> error, not silent fall-open.

        The strict-verify contract: when the drive has no identity
        info and the probe can't supply one either, refuse to assume
        the drive belongs to the connected board.  Silently returning
        *drive_path* would land the deploy on whatever ``candidates[0]``
        happened to be, and on a multi-CP-board host that's often the
        wrong board.
        """
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [drive],
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[_RAW_REPL_PROMPT],  # connect only; probe will hit empty
        )
        with pytest.raises(
            CircuitpythonTransportError,
            match="no boot_out.txt",
        ):
            transport._verify_drive_for_board(drive)

    def test_refuses_when_probe_unidentifiable_and_two_real_boards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """boot_out.txt present but the probe gives no identity, and a second
        CIRCUITPY* mount also carries boot_out.txt -> refuse rather than risk
        a wrong-board wipe, naming both candidate paths."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            f"Adafruit CircuitPython 10.2.0 on 2026-01-01; {_TEST_BOOT_MACHINE}\n"
            f"Board ID:test_board\nUID:{_TEST_BOOT_UID}\n",
            encoding="utf-8",
        )
        sibling = tmp_path / "CIRCUITPY 1"
        sibling.mkdir()
        (sibling / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0 on 2026-01-01; Other Board\n"
            "Board ID:other_board\nUID:DEADBEEF\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [drive, sibling],
        )
        monkeypatch.setattr(
            CircuitpythonTransport, "probe_implementation", lambda self: None,
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[_RAW_REPL_PROMPT],
        )
        with pytest.raises(
            CircuitpythonTransportError, match="cannot confirm",
        ) as caught:
            transport._verify_drive_for_board(drive)
        # The refusal names both candidate paths so the user can see which
        # mounts it's worried about, not just a bare count.
        message = str(caught.value)
        assert str(drive) in message
        assert str(sibling) in message

    def test_proceeds_when_sibling_mount_is_empty_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One real board plus a bare (boot_out.txt-less) CIRCUITPY* stale
        mount is unambiguous: only the real board counts toward the
        ambiguity check, so the deploy proceeds instead of false-refusing."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            f"Adafruit CircuitPython 10.2.0 on 2026-01-01; {_TEST_BOOT_MACHINE}\n"
            f"Board ID:test_board\nUID:{_TEST_BOOT_UID}\n",
            encoding="utf-8",
        )
        stale = tmp_path / "CIRCUITPY 1"
        stale.mkdir()  # bare placeholder, no boot_out.txt
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [drive, stale],
        )
        monkeypatch.setattr(
            CircuitpythonTransport, "probe_implementation", lambda self: None,
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[_RAW_REPL_PROMPT],
        )
        assert transport._verify_drive_for_board(drive) == drive

    def test_returns_drive_when_probe_unidentifiable_but_single_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A single mounted CIRCUITPY* volume is unambiguous, so an
        unverifiable probe still returns the drive (single-board host)."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            f"Adafruit CircuitPython 10.2.0 on 2026-01-01; {_TEST_BOOT_MACHINE}\n"
            f"Board ID:test_board\nUID:{_TEST_BOOT_UID}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [drive],
        )
        monkeypatch.setattr(
            CircuitpythonTransport, "probe_implementation", lambda self: None,
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[_RAW_REPL_PROMPT],
        )
        assert transport._verify_drive_for_board(drive) == drive

    def test_auto_corrects_when_boot_out_missing_but_sibling_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """boot_out.txt missing on drive_path + matching sibling -> swap silently.

        Common trigger: the last deploy wiped boot_out.txt via rsync
        --delete and the soft-reboot afterwards didn't regenerate it.
        On a multi-board host, the right drive is still identified
        via whichever sibling's boot_out.txt still matches the probed
        connected board.
        """
        wrong_drive = tmp_path / "CIRCUITPY"
        wrong_drive.mkdir()  # no boot_out.txt
        right_drive = tmp_path / "CIRCUITPY 1"
        right_drive.mkdir()
        (right_drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [wrong_drive, right_drive],
        )
        transport, _ = self._make_transport(
            drive_path=str(wrong_drive),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        corrected = transport._verify_drive_for_board(wrong_drive)
        assert corrected == right_drive

    def test_returns_unchanged_on_machine_match(
        self, tmp_path: Path,
    ) -> None:
        """boot_out.txt machine matches probe -> original path returned."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2"),
            encoding="utf-8",
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        assert transport._verify_drive_for_board(drive) == drive

    def test_auto_corrects_silently_to_sibling_mount_on_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Wrong drive + a sibling mount that matches -> silent correction.

        Auto-correction on success is silent (the warning was noise
        for the common two-board bench setup where macOS renames the
        second CIRCUITPY mount).  Only the no-sibling-match path
        raises.
        """
        wrong_drive = tmp_path / "CIRCUITPY"
        wrong_drive.mkdir()
        (wrong_drive / "boot_out.txt").write_text(
            self._boot_out("Raspberry Pi Pico W with rp2040"),
            encoding="utf-8",
        )
        right_drive = tmp_path / "CIRCUITPY 1"
        right_drive.mkdir()
        (right_drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [wrong_drive, right_drive],
        )
        transport, _ = self._make_transport(
            drive_path=str(wrong_drive),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        corrected = transport._verify_drive_for_board(wrong_drive)
        assert corrected == right_drive
        captured = capsys.readouterr()
        assert captured.out == "", (
            f"auto-correction must be silent on success; got: {captured.out!r}"
        )

    def test_raises_when_no_matching_mount_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wrong drive + no sibling match -> error with devices.yml guidance."""
        wrong_drive = tmp_path / "CIRCUITPY"
        wrong_drive.mkdir()
        (wrong_drive / "boot_out.txt").write_text(
            self._boot_out("Raspberry Pi Pico W with rp2040"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [wrong_drive],
        )
        transport, _ = self._make_transport(
            drive_path=str(wrong_drive),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        with pytest.raises(
            CircuitpythonTransportError,
            match="does not match the connected board",
        ):
            transport._verify_drive_for_board(wrong_drive)

    def test_fails_open_when_probe_unavailable(
        self, tmp_path: Path,
    ) -> None:
        """Probe returns None -> verification proceeds with original path."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2"),
            encoding="utf-8",
        )
        # Probe response with no __CHU_IMPL__ marker -> parse returns None.
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[
                _RAW_REPL_PROMPT,
                b"OK\x04\x04>",  # empty stdout -> no marker
            ],
        )
        assert transport._verify_drive_for_board(drive) == drive

    def test_read_boot_out_identity_extracts_machine_suffix(
        self, tmp_path: Path,
    ) -> None:
        """``on DATE; MACHINE`` suffix is returned, malformed files -> None."""
        from chumicro_deploy.circuitpy_drive import (
            _read_boot_out_identity,
        )

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0 on 2026-01-02; Foo Board with xyz\n"
            "Board ID:foo\n",
            encoding="utf-8",
        )
        _uid, machine = _read_boot_out_identity(drive)
        assert machine == "Foo Board with xyz"

        # Missing file: both fields None.
        empty = tmp_path / "OTHER"
        empty.mkdir()
        assert _read_boot_out_identity(empty) == (None, None)

        # Malformed first line (no semicolon): machine is None.
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "boot_out.txt").write_text("weird line\n", encoding="utf-8")
        _uid_bad, machine_bad = _read_boot_out_identity(bad)
        assert machine_bad is None

    def test_find_circuitpy_drive_for_machine_scans_mounts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scans mounts and returns the first one whose machine matches."""
        from chumicro_deploy.circuitpy_drive import (
            find_circuitpy_drive_for_machine,
        )

        first = tmp_path / "CIRCUITPY"
        first.mkdir()
        (first / "boot_out.txt").write_text(
            self._boot_out("Raspberry Pi Pico W with rp2040"),
            encoding="utf-8",
        )
        second = tmp_path / "CIRCUITPY 1"
        second.mkdir()
        (second / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [first, second],
        )
        assert find_circuitpy_drive_for_machine(
            "S2Mini with ESP32S2-S2FN4R2",
        ) == str(second)
        assert find_circuitpy_drive_for_machine("") is None
        assert find_circuitpy_drive_for_machine("Not A Board") is None

    def test_uid_match_preferred_over_machine_when_both_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two identical-machine boards: UID disambiguates, machine alone can't.

        Regression guard for the "two identical boards connected at
        once" case: both drives report the same ``_machine`` string,
        but ``UID:`` in ``boot_out.txt`` (and ``microcontroller.cpu.uid``
        over REPL) is unique.  The verifier must pick the UID-matching
        mount, even though the configured drive's machine-string
        already matches the probe.

        Implicit branch check: if the machine-fallback fired instead
        of the UID branch, ``drive_identity == probe_identity`` would
        short-circuit at the equal-strings guard and return the
        configured (wrong) drive.  Asserting ``corrected == sibling``
        therefore proves the UID branch ran.
        """
        configured = tmp_path / "CIRCUITPY"
        configured.mkdir()
        (configured / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="AAAAAAAA"),
            encoding="utf-8",
        )
        sibling = tmp_path / "CIRCUITPY 1"
        sibling.mkdir()
        (sibling / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="BBBBBBBB"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [configured, sibling],
        )
        transport, _ = self._make_transport(
            drive_path=str(configured),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response(
                    "S2Mini with ESP32S2-S2FN4R2", uid="BBBBBBBB",
                ),
            ],
        )
        corrected = transport._verify_drive_for_board(configured)
        assert corrected == sibling

    def test_machine_fallback_when_probe_has_no_uid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Old firmware leaves the probe with no uid, so the machine-string fallback kicks in."""
        wrong = tmp_path / "CIRCUITPY"
        wrong.mkdir()
        (wrong / "boot_out.txt").write_text(
            self._boot_out("Raspberry Pi Pico W with rp2040", uid="11111111"),
            encoding="utf-8",
        )
        right = tmp_path / "CIRCUITPY 1"
        right.mkdir()
        (right / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="22222222"),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive"
            "._circuitpy_volume_candidates",
            lambda: [wrong, right],
        )
        transport, _ = self._make_transport(
            drive_path=str(wrong),
            reads=[
                _RAW_REPL_PROMPT,
                # No uid in the probe response, so machine fallback applies.
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        assert transport._verify_drive_for_board(wrong) == right

    def test_returns_unchanged_when_uid_matches(
        self, tmp_path: Path,
    ) -> None:
        """UID on drive matches probe UID, no correction, no warning."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="487F301F0224"),
            encoding="utf-8",
        )
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[
                _RAW_REPL_PROMPT,
                self._probe_response(
                    "S2Mini with ESP32S2-S2FN4R2", uid="487F301F0224",
                ),
            ],
        )
        assert transport._verify_drive_for_board(drive) == drive

    def test_read_boot_out_identity_extracts_uid_line(
        self, tmp_path: Path,
    ) -> None:
        """``UID:`` line is extracted and normalized to uppercase."""
        from chumicro_deploy.circuitpy_drive import (
            _read_boot_out_identity,
        )

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="487f301f0224"),
            encoding="utf-8",
        )
        uid, _machine = _read_boot_out_identity(drive)
        assert uid == "487F301F0224"

        # File without UID line: uid is None even though machine parses.
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0 on 2026-01-02; Foo Board\n"
            "Board ID:foo\n",
            encoding="utf-8",
        )
        uid_bad, machine_bad = _read_boot_out_identity(bad)
        assert uid_bad is None
        assert machine_bad == "Foo Board"

    def test_find_circuitpy_drive_for_uid_scans_mounts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scans mounts and matches by UID (case-insensitive)."""
        from chumicro_deploy.circuitpy_drive import (
            find_circuitpy_drive_for_uid,
        )

        first = tmp_path / "CIRCUITPY"
        first.mkdir()
        (first / "boot_out.txt").write_text(
            self._boot_out("Board A", uid="AAAA1111"),
            encoding="utf-8",
        )
        second = tmp_path / "CIRCUITPY 1"
        second.mkdir()
        (second / "boot_out.txt").write_text(
            self._boot_out("Board B", uid="BBBB2222"),
            encoding="utf-8",
        )
        # find_circuitpy_drive_for_uid is a module-level helper that
        # scans circuitpy_drive._circuitpy_volume_candidates() directly,
        # not transport-internal, so monkeypatch the module-level fn.
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [first, second],
        )
        # Lower-case input matches upper-case UID in boot_out.txt.
        assert find_circuitpy_drive_for_uid("bbbb2222") == str(second)
        assert find_circuitpy_drive_for_uid("") is None
        assert find_circuitpy_drive_for_uid("CCCC3333") is None


class TestFormatProbeError:
    """_format_probe_error translates probe OSErrors into recovery-
    classifier-friendly messages."""

    def test_enospc_says_drive_is_full(self) -> None:
        error = OSError(errno.ENOSPC, "No space left on device")
        message = _format_probe_error(Path("/Volumes/CIRCUITPY"), error)
        assert "is full" in message
        assert "No space left on device" in message
        assert "not found" not in message

    def test_erofs_says_drive_is_read_only(self) -> None:
        error = OSError(errno.EROFS, "Read-only file system")
        message = _format_probe_error(Path("/Volumes/CIRCUITPY"), error)
        assert "is read-only" in message
        assert "Read-only file system" in message
        assert "not found" not in message

    def test_eacces_keeps_legacy_not_found_or_not_writable(self) -> None:
        # Stale Finder-eject mounts surface as EACCES on the probe.
        # The classifier needs the wrap phrase to route them to
        # CIRCUITPY_DRIVE_MISSING (not FLASH_COPY_FAILED).
        error = PermissionError(errno.EACCES, "Permission denied")
        message = _format_probe_error(Path("/Volumes/CIRCUITPY"), error)
        assert "not found or not writable" in message
        assert "Permission denied" in message

    def test_unknown_errno_uses_legacy_wrapper(self) -> None:
        error = OSError(errno.EIO, "Input/output error")
        message = _format_probe_error(Path("/Volumes/CIRCUITPY"), error)
        # EIO is not specifically translated, the underlying text still
        # carries the signal the classifier needs ("input/output error"
        # is in _FLASH_DRIVE_STATE_PATTERNS).
        assert "not found or not writable" in message
        assert "Input/output error" in message


class TestListFilesInScopeAndDelete:
    """CP transport's diff-deploy primitives (multi-project-staging replacement)."""

    def test_ram_mode_returns_empty(self) -> None:
        """RAM-mode never wrote to flash, so list_files_in_scope yields nothing."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            time=FakeTime(),
        )
        assert transport.list_files_in_scope() == []

    def test_ram_mode_delete_no_op(self) -> None:
        """RAM-mode delete_files is a no-op (nothing on flash to remove)."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            time=FakeTime(),
        )
        # Doesn't raise even with paths supplied.
        transport.delete_files(["/lib/foo.py"])

    def test_flash_mode_lists_in_scope_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Walks the CIRCUITPY drive + filters to deploy-scope paths."""
        # Plant a mix of in-scope and out-of-scope files on a fake drive.
        (tmp_path / "code.py").write_text("# code")
        (tmp_path / "active.py").write_text("PROJECT_NAME = 'x'")
        (tmp_path / "settings.toml").write_text("WIFI = '...'")  # out of scope
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "foo.py").write_text("x = 1")
        (tmp_path / "lib" / "nested").mkdir()
        (tmp_path / "lib" / "nested" / "bar.py").write_text("y = 2")
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "log.txt").write_text("user data")  # out of scope

        # boot_out.txt is planted by the helper with valid identity so
        # ``_verify_drive_for_board`` cheap-paths.  It's still filtered
        # out of the scope listing because it's not a deploy-scope name.
        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        result = sorted(transport.list_files_in_scope())
        assert result == [
            "/active.py",
            "/code.py",
            "/lib/foo.py",
            "/lib/nested/bar.py",
        ]

    def test_flash_mode_lists_returns_empty_on_missing_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive resolution failure leaves an empty listing (no exception)."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [],
        )
        assert transport.list_files_in_scope() == []

    def test_flash_mode_deletes_paths_under_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "lib").mkdir()
        target = tmp_path / "lib" / "stale.py"
        target.write_text("# old")
        keeper = tmp_path / "lib" / "keep.py"
        keeper.write_text("# keep")

        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.delete_files(["/lib/stale.py", "/lib/missing.py"])
        # Stale removed, missing tolerated silently, keeper survives.
        assert not target.exists()
        assert keeper.exists()

    def test_delete_reaps_emptied_package_dirs_not_lib_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An emptied `/lib/<pkg>/` is pruned, live siblings + lib root stay.

        Regression: unlink removes files but not directories, so a
        package whose every file was stale left an empty husk.  A
        stale `import <pkg>` then failed mid-package instead of
        cleanly.  The diff path must reap the husk (rsync --delete
        would have).
        """
        lib = tmp_path / "lib"
        (lib / "pkg" / "nested").mkdir(parents=True)
        (lib / "pkg" / "__init__.py").write_text("# pkg")
        (lib / "pkg" / "nested" / "deep.py").write_text("# deep")
        (lib / "keep").mkdir()
        (lib / "keep" / "__init__.py").write_text("# survives")

        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.delete_files([
            "/lib/pkg/__init__.py",
            "/lib/pkg/nested/deep.py",
        ])
        # Husk and its nested empty dir reaped, deepest-first.
        assert not (lib / "pkg" / "nested").exists()
        assert not (lib / "pkg").exists()
        # The scope root is never removed, and a package that still
        # holds a live file is left untouched.
        assert lib.is_dir()
        assert (lib / "keep" / "__init__.py").exists()

    def test_delete_reaps_root_level_empty_pkg_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A root-level orphan `/<pkg>/` (from a prior deploy convention) gets reaped.

        An empty ``/<pkg>/`` at root resolves ``import <pkg>`` to a
        PEP 420 namespace package and shadows the populated
        ``/lib/<pkg>/`` underneath in ``sys.path``.  The reap targets
        the whole deploy scope, not just ``/lib/``, so a board
        carrying the husk from an older deploy layout has it cleaned
        out alongside the lib-side stale files.
        """
        (tmp_path / "chumicro_timing").mkdir()
        (tmp_path / "chumicro_timing" / "old.py").write_text("# stale")
        (tmp_path / "lib" / "chumicro_timing").mkdir(parents=True)
        (tmp_path / "lib" / "chumicro_timing" / "__init__.py").write_text(
            "# new payload",
        )

        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.delete_files(["/chumicro_timing/old.py"])

        # Husk reaped, no more shadowing namespace package at root.
        assert not (tmp_path / "chumicro_timing").exists()
        # New payload survives (it has a live file).
        assert (tmp_path / "lib" / "chumicro_timing" / "__init__.py").is_file()

    def test_delete_skips_dot_prefixed_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """macOS noise (``.Spotlight-V100`` etc.) isn't reaped.

        Mirrors ``_list_scope_on_drive``'s dot-prefix filter.  These
        entries are managed by the host OS and outside the deploy's
        scope.  Reaping an empty one would be harmless functionally
        but would burn FAT writes on a class of files we deliberately
        don't track.
        """
        (tmp_path / ".Spotlight-V100").mkdir()  # empty macOS noise
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "old.py").write_text("# stale")

        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.delete_files(["/lib/old.py"])

        # Dot-prefixed entry survives even though it's empty.
        assert (tmp_path / ".Spotlight-V100").is_dir()

    def test_delete_keeps_dir_that_still_has_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """rmdir only removes empty dirs, so a partially-cleared pkg stays."""
        lib = tmp_path / "lib"
        (lib / "pkg").mkdir(parents=True)
        (lib / "pkg" / "gone.py").write_text("# stale")
        (lib / "pkg" / "stays.py").write_text("# live")

        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.delete_files(["/lib/pkg/gone.py"])
        assert not (lib / "pkg" / "gone.py").exists()
        assert (lib / "pkg").is_dir()
        assert (lib / "pkg" / "stays.py").exists()

    def test_flash_mode_delete_with_empty_paths_returns_immediately(
        self, tmp_path: Path,
    ) -> None:
        """delete_files([]) shouldn't even resolve the drive."""
        # Pass a clearly-missing drive path; if the call tried to resolve,
        # it would silently succeed (delete is best-effort), so this is a
        # sanity guard rather than a strict assertion.
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
        )
        transport.delete_files([])  # no exception, no error


class TestClearEntrypoints:
    """CP transport's pre-soft-reset entrypoint clear (sweep race fix)."""

    def test_ram_mode_is_no_op(self) -> None:
        """RAM mode never persists an entrypoint, so nothing to clear."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0", mode="ram", time=FakeTime(),
        )
        transport.clear_entrypoints()  # no drive resolve, no raise

    def test_flash_mode_unlinks_code_and_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stale code.py + main.py are both removed and verified gone."""
        (tmp_path / "code.py").write_text("print('stale')")
        (tmp_path / "main.py").write_text("print('stale')")
        keeper = tmp_path / "lib"
        keeper.mkdir()
        (keeper / "thing.py").write_text("x = 1")
        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.clear_entrypoints()
        assert not (tmp_path / "code.py").exists()
        assert not (tmp_path / "main.py").exists()
        assert (keeper / "thing.py").exists()  # untouched

    def test_flash_mode_absent_entrypoints_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No code.py/main.py present, clears cleanly, no raise."""
        _plant_verifiable_circuitpy(tmp_path, monkeypatch)
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [tmp_path],
        )
        transport.clear_entrypoints()  # no raise

    def test_flash_mode_missing_drive_returns_quietly(self) -> None:
        """Unresolvable drive falls to a no-op (soft_reset path handles it)."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            time=FakeTime(),
            drive_scanner=lambda: [],
        )
        transport.clear_entrypoints()  # no raise

    def test_list_files_in_scope_auto_corrects_stale_drive_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``circuitpy_drive_path`` pointing at the wrong board's drive
        is silently auto-corrected.  List returns the connected board's
        files, not the unrelated mount's.

        Multi-board macOS bench: a ``CIRCUITPY 1`` rename swap leaves
        ``devices.yml`` ``circuitpy_drive_path`` stale, and without
        verify the diff layer reports zero stale files because it's
        looking at the other board.
        """
        wrong_drive = tmp_path / "CIRCUITPY"
        wrong_drive.mkdir()
        (wrong_drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; "
            "Raspberry Pi Pico W with rp2040\n"
            "Board ID:raspberry_pi_pico_w\n"
            "UID:E6614103E7174624\n",
            encoding="utf-8",
        )
        (wrong_drive / "wrong_only.py").write_text("x = 1")

        right_drive = tmp_path / "CIRCUITPY 1"
        right_drive.mkdir()
        (right_drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.1.4 on 2026-03-09; "
            "S2Mini with ESP32S2-S2FN4R2\n"
            "Board ID:lolin_s2_mini\n"
            "UID:84722E7490C3\n",
            encoding="utf-8",
        )
        (right_drive / "code.py").write_text("# right code")
        (right_drive / "lib").mkdir()
        (right_drive / "lib" / "right_only.py").write_text("y = 2")

        # The auto-correct path goes through circuitpy_drive's module-
        # level find_circuitpy_drive_for_uid helper, which uses the
        # module-global _circuitpy_volume_candidates, not the
        # transport's drive_scanner.  Patch both surfaces so the
        # auto-correct sees both candidates.
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [wrong_drive, right_drive],
        )

        # Probe response identifies the connected board as the Lolin S2,
        # whose mount is actually at right_drive.
        probe_marker = (
            "OK"
            "__CHU_IMPL__:circuitpython|10.1.4|S2Mini with ESP32S2-S2FN4R2\n"
            "__CHU_UID__:84722E7490C3\n"
            "\x04\x04>"
        )
        port = FakeSerialPort(read_responses=[
            _RAW_REPL_PROMPT,
            probe_marker.encode("utf-8"),
        ])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=lambda **kw: port,
            time=FakeTime(),
            drive_scanner=lambda: [wrong_drive, right_drive],
        )
        transport.connect()
        listed = sorted(transport.list_files_in_scope())
        # Right-drive contents only, wrong-drive's `wrong_only.py` is absent.
        assert listed == ["/code.py", "/lib/right_only.py"]

    def test_delete_files_auto_corrects_stale_drive_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """delete_files unlinks from the connected board's mount, not
        the stale ``circuitpy_drive_path``'s.  Same risk class as
        list_files_in_scope, more dangerous because it is destructive."""
        wrong_drive = tmp_path / "CIRCUITPY"
        wrong_drive.mkdir()
        (wrong_drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; "
            "Raspberry Pi Pico W with rp2040\n"
            "Board ID:raspberry_pi_pico_w\n"
            "UID:E6614103E7174624\n",
            encoding="utf-8",
        )
        (wrong_drive / "lib").mkdir()
        wrong_target = wrong_drive / "lib" / "stale.py"
        wrong_target.write_text("# wrong board — must NOT be deleted")

        right_drive = tmp_path / "CIRCUITPY 1"
        right_drive.mkdir()
        (right_drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.1.4 on 2026-03-09; "
            "S2Mini with ESP32S2-S2FN4R2\n"
            "Board ID:lolin_s2_mini\n"
            "UID:84722E7490C3\n",
            encoding="utf-8",
        )
        (right_drive / "lib").mkdir()
        right_target = right_drive / "lib" / "stale.py"
        right_target.write_text("# right board — should be deleted")

        # Same caveat as test_list_files_in_scope_auto_corrects_stale_drive_path
        # above.  The auto-correct uses the module-level candidates fn.
        monkeypatch.setattr(
            "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
            lambda: [wrong_drive, right_drive],
        )

        probe_marker = (
            "OK"
            "__CHU_IMPL__:circuitpython|10.1.4|S2Mini with ESP32S2-S2FN4R2\n"
            "__CHU_UID__:84722E7490C3\n"
            "\x04\x04>"
        )
        port = FakeSerialPort(read_responses=[
            _RAW_REPL_PROMPT,
            probe_marker.encode("utf-8"),
        ])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=lambda **kw: port,
            time=FakeTime(),
            drive_scanner=lambda: [wrong_drive, right_drive],
        )
        transport.connect()
        transport.delete_files(["/lib/stale.py"])
        # The connected-board mount's file got deleted, the stale path's didn't.
        assert not right_target.exists()
        assert wrong_target.exists(), (
            "delete_files unlinked from the wrong board's drive — "
            "stale circuitpy_drive_path was not auto-corrected"
        )


class TestWipeFilesystem:
    """`wipe_filesystem()` drives `storage.erase_filesystem()` then re-connects."""

    def test_ram_mode_is_no_op(self) -> None:
        """RAM mode never wrote to flash, so wipe is a silent no-op."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0", mode="ram", time=FakeTime(),
        )
        # No exception, no port writes (no port even exists).
        transport.wipe_filesystem()

    def test_flash_mode_without_connect_raises(self) -> None:
        """Calling wipe before connect surfaces a precise error."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0", mode="flash", time=FakeTime(),
        )
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            transport.wipe_filesystem()

    def test_flash_mode_drives_erase_and_reconnects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sends erase_filesystem, swallows the dropped REPL, re-opens port."""
        # First port: serves connect() then dies during the wipe REPL call
        # (no further read responses, so _send_repl_command raises, which we
        # swallow as expected behavior).  Second port: serves the post-wipe
        # reconnect.
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]

        def multi_port_factory(**kwargs):
            return ports.pop(0)

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=multi_port_factory,
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        transport.wipe_filesystem()

        # The wipe script was issued on the first port.
        wipe_writes = b"".join(first_port.writes)
        assert b"storage.erase_filesystem" in wipe_writes
        # First port closed, second port serves the re-connect.
        assert first_port.closed
        assert ports == []  # both ports consumed by the factory

    def test_flash_mode_close_failure_is_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failure tearing the dropped port down doesn't block re-connect."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()

        class _UncloseablePort(FakeSerialPort):
            def close(self) -> None:
                raise OSError("simulated close failure")

        first_port = _UncloseablePort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_: ports.pop(0),
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        transport.wipe_filesystem()  # close failure swallowed, re-connect runs
        assert ports == []

    def test_flash_mode_waits_for_drive_already_mounted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive mounted at the moment serial reconnects: no extra waits."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()

        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]
        fake_time = FakeTime()
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_: ports.pop(0),
            time=fake_time,
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        before = fake_time.monotonic()
        transport.wipe_filesystem()
        elapsed = fake_time.monotonic() - before
        # Reboot settle + (any) serial reconnect polling, but no FAT-remount
        # polling because the drive is already mounted.
        assert elapsed < _WIPE_FAT_REMOUNT_TIMEOUT_SECONDS
        assert ports == []

    def test_flash_mode_waits_for_drive_remount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive that appears mid-poll succeeds without raising."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()  # pre-existing on disk, but masked for first probes
        # Pretend the FAT volume hasn't remounted yet for the first two
        # poll probes, then "remount" by letting the real is_dir win.
        original_is_dir = Path.is_dir
        probe_count = {"value": 0}

        def staged_is_dir(self: Path) -> bool:
            if self == drive:
                probe_count["value"] += 1
                if probe_count["value"] < 3:
                    return False
            return original_is_dir(self)

        monkeypatch.setattr(Path, "is_dir", staged_is_dir)

        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_: ports.pop(0),
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        transport.wipe_filesystem()
        # Probed at least 3 times, first two masked, third returned True.
        assert probe_count["value"] >= 3

    def test_flash_mode_drive_never_remounts_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive that never reappears within budget raises a clear error."""
        drive = tmp_path / "CIRCUITPY"  # never created

        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_: ports.pop(0),
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        with pytest.raises(
            CircuitpythonTransportError,
            match="CIRCUITPY drive not mounted",
        ):
            transport.wipe_filesystem()

    def test_flash_mode_drive_present_but_unwritable_polls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drive directory exists but probe writes EACCES until macOS settles."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        # First two probe writes hit EACCES (drive mounted but not yet
        # writable post-remount), third succeeds.
        original_write_bytes = Path.write_bytes
        write_attempts = {"value": 0}

        def staged_write_bytes(self: Path, data: bytes) -> int:
            if self.name == ".chu-probe":
                write_attempts["value"] += 1
                if write_attempts["value"] < 3:
                    raise PermissionError(
                        errno.EACCES, "Permission denied", str(self),
                    )
            return original_write_bytes(self, data)

        monkeypatch.setattr(Path, "write_bytes", staged_write_bytes)

        first_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        second_port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])
        ports = [first_port, second_port]
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            timeout=0.05,
            serial_port_factory=lambda **_: ports.pop(0),
            time=FakeTime(),
            drive_scanner=lambda: [drive],
        )
        transport.connect()
        transport.wipe_filesystem()
        assert write_attempts["value"] >= 3

class TestListScopeOnDriveHelper:
    """Module-level CIRCUITPY-walk helper used by `list_files_in_scope`."""

    def test_includes_canonical_state_files(self, tmp_path: Path) -> None:
        from chumicro_deploy.circuitpy_drive import _list_scope_on_drive

        for filename in ("code.py", "main.py", "active.py", "runtime_config.msgpack"):
            (tmp_path / filename).write_text("")
        result = sorted(_list_scope_on_drive(tmp_path))
        assert result == [
            "/active.py",
            "/code.py",
            "/main.py",
            "/runtime_config.msgpack",
        ]

    def test_omits_user_managed_root_files(self, tmp_path: Path) -> None:
        from chumicro_deploy.circuitpy_drive import _list_scope_on_drive

        # In-scope.
        (tmp_path / "code.py").write_text("")
        # Out-of-scope.
        (tmp_path / "settings.toml").write_text("")
        (tmp_path / "secrets.toml").write_text("")
        (tmp_path / "boot.py").write_text("")
        (tmp_path / "photo.jpg").write_bytes(b"")
        result = sorted(_list_scope_on_drive(tmp_path))
        assert result == ["/code.py"]

    def test_walks_lib_recursively(self, tmp_path: Path) -> None:
        from chumicro_deploy.circuitpy_drive import _list_scope_on_drive

        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "a.py").write_text("")
        (tmp_path / "lib" / "deep").mkdir()
        (tmp_path / "lib" / "deep" / "b.py").write_text("")
        result = sorted(_list_scope_on_drive(tmp_path))
        assert result == ["/lib/a.py", "/lib/deep/b.py"]

    def test_empty_drive_returns_empty(self, tmp_path: Path) -> None:
        from chumicro_deploy.circuitpy_drive import _list_scope_on_drive

        assert _list_scope_on_drive(tmp_path) == []


def _build_dual_runtime_pkg(source_root: Path) -> Path:
    """Create a synthetic package with CP, MP, and unmarked files."""
    pkg = source_root / "chumicro_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# universal\n")
    (pkg / "shared.py").write_text("# universal\n")
    adapters = pkg / "_adapters"
    adapters.mkdir()
    (adapters / "__init__.py").write_text("")
    (adapters / "cp.py").write_text(
        '__chumicro_runtimes__ = ("circuitpython",)\n',
    )
    (adapters / "mp.py").write_text(
        '__chumicro_runtimes__ = ("micropython",)\n',
    )
    return pkg


class TestRuntimeFilteringRamMode:
    """RAM-mode staging drops files marked for other runtimes."""

    def test_ram_stage_excludes_micropython_files(self, tmp_path: Path) -> None:
        source_root = tmp_path / "src"
        source_root.mkdir()
        _build_dual_runtime_pkg(source_root)
        harness = tmp_path / "harness"
        harness.mkdir()
        (harness / "harness_pkg").mkdir()
        (harness / "harness_pkg" / "__init__.py").write_text("")
        transport = CircuitpythonTransport(
            "/dev/null",
            serial_port_factory=lambda **_: FakeSerialPort(),
            time=FakeTime(),
        )
        transport.stage([source_root], test_files=[], harness_source=harness)
        staged = transport.staged_sources or []
        names = {module_name for module_name, _ in staged}
        assert "chumicro_pkg._adapters.cp" in names
        assert "chumicro_pkg._adapters.mp" not in names
        # Universal files survive.
        assert "chumicro_pkg.shared" in names

    def test_target_runtime_default_is_circuitpython(self) -> None:
        """The transport's identity sets the filter, no kwarg needed."""
        transport = CircuitpythonTransport(
            "/dev/null",
            serial_port_factory=lambda **_: FakeSerialPort(),
            time=FakeTime(),
        )
        assert transport._target_runtime == "circuitpython"


class TestRuntimeFilteringFlashStaging:
    """Flash-mode local staging drops files marked for other runtimes."""

    def test_build_local_staging_tree_excludes_mp(self, tmp_path: Path) -> None:
        source_root = tmp_path / "src"
        source_root.mkdir()
        _build_dual_runtime_pkg(source_root)
        harness = tmp_path / "harness"
        harness.mkdir()
        # Empty harness, focus on the source dir filtering.
        staging = tmp_path / "staging"
        staging.mkdir()
        transport = CircuitpythonTransport(
            "/dev/null",
            serial_port_factory=lambda **_: FakeSerialPort(),
            time=FakeTime(),
        )
        transport._build_local_staging_tree(
            staging, [source_root], test_files=[], harness_source=harness,
        )
        cp_path = staging / "lib" / "chumicro_pkg" / "_adapters" / "cp.py"
        mp_path = staging / "lib" / "chumicro_pkg" / "_adapters" / "mp.py"
        assert cp_path.exists()
        assert not mp_path.exists()
