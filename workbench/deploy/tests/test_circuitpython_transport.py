"""Tests for CircuitpythonTransport — pyserial raw REPL transport."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.circuitpython_transport import (
    _CTRL_A,
    _CTRL_C,
    _CTRL_D,
    _RAW_REPL_PROMPT,
    CircuitpythonTransport,
    CircuitpythonTransportError,
    find_circuitpy_drive,
)
from chumicro_deploy.testing import (
    FakeSerialPort,
    FakeTime,
)

#: Shorthand for the standard autoreload REPL acknowledgement.
_OK_RESPONSE = b"OK\x04\x04>"


def _repl_response(stdout: bytes = b"", stderr: bytes = b"") -> bytes:
    """Build a raw-REPL response with *stdout* / *stderr* payloads."""
    return b"OK" + stdout + b"\x04" + stderr + b"\x04>"


class TestConnect:
    """Tests for CircuitpythonTransport.connect."""

    def test_connect_sends_interrupt_and_enters_raw_repl(self) -> None:
        """connect() should send Ctrl-C×2 then Ctrl-A."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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
        def factory(**kwargs):
            raise OSError("port not found")

        transport = CircuitpythonTransport(
            "/dev/ttyNONE",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            captured_kwargs.update(kwargs)
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            baudrate=9600,
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()

        assert captured_kwargs.get("baudrate") == 9600


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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        # Single \x04 followed by ">" — valid but minimal response.
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, b"OKhello\x04\x04>"],
        )

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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
                # Missing "OK" prefix — _send_repl_command will raise;
                # probe must swallow it.
                b"nope\x04\x04>",
            ],
        )

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()

        assert transport.probe_implementation() is None

        transport.disconnect()


class TestReset:
    """Tests for CircuitpythonTransport.reset."""

    def test_reset_sends_ctrl_d(self) -> None:
        """reset() should send Ctrl-D for soft reboot."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()
        port.writes.clear()

        transport.reset()

        assert _CTRL_D in port.writes

    def test_reset_without_connect_is_safe(self) -> None:
        """reset() without a connected port should not raise."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )
        transport.reset()  # Should not raise.


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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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


class TestDisconnect:
    """Tests for CircuitpythonTransport.disconnect."""

    def test_disconnect_closes_port(self) -> None:
        """disconnect() should close the serial port."""
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT])

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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
    ) -> CircuitpythonTransport:
        """Create a flash-mode transport with a fake serial port."""
        def factory(**kwargs):
            return port

        return CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            circuitpy_drive_path=circuitpy_drive_path,
            serial_port_factory=factory,
            time=FakeTime(),
        )

    def test_flash_mode_stores_mode(self) -> None:
        """Flash transport should record the mode."""
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            circuitpy_drive_path="/Volumes/CIRCUITPY",
            serial_port_factory=lambda **kw: None,
            time=FakeTime(),
        )
        assert transport.mode == "flash"

    def test_flash_stage_raises_when_no_drive_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should raise when drive is not found."""
        # Ensure auto-detection finds nothing.
        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport"
            ".find_circuitpy_drive",
            lambda: None,
        )
        # Extra responses for disconnect()'s _enter_raw_repl + autoreload restore.
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, _RAW_REPL_PROMPT, _OK_RESPONSE],
        )

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=factory,
            time=FakeTime(),
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
    ) -> None:
        """stage() in flash mode should raise when drive path doesn't exist."""
        # Responses: connect + _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, _RAW_REPL_PROMPT, _OK_RESPONSE],
        )

        transport = self._make_flash_transport(
            port, str(tmp_path / "NO_DRIVE"),
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

    def test_flash_stage_raises_when_drive_is_unwritable(
        self, tmp_path: Path,
    ) -> None:
        """stage() should catch a stale/unwritable mount via the probe.

        On macOS, ejecting CIRCUITPY from Finder can leave
        ``/Volumes/CIRCUITPY`` as a directory that ``is_dir()`` accepts
        but that raises ``PermissionError`` on write.  Simulated here
        by chmod-ing tmp_path to read-only so the probe's
        ``write_bytes()`` fails.  The wrapped error preserves the
        "CIRCUITPY drive not found" substring so
        :func:`classify_deploy_failure` routes it to
        :attr:`DeployFailureKind.CIRCUITPY_DRIVE_MISSING`.
        """
        import os

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        port = FakeSerialPort(
            read_responses=[_RAW_REPL_PROMPT, _RAW_REPL_PROMPT, _OK_RESPONSE],
        )
        transport = self._make_flash_transport(port, str(drive))
        transport.connect()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        original_mode = drive.stat().st_mode
        os.chmod(drive, 0o500)
        try:
            with pytest.raises(
                CircuitpythonTransportError,
                match="CIRCUITPY drive not found or not writable",
            ):
                transport.stage([source_dir], [], harness_dir)
        finally:
            os.chmod(drive, original_mode)

        transport.disconnect()

    def test_flash_stage_copies_packages_to_lib(
        self, tmp_path: Path,
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

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
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

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
        transport.connect()
        transport.stage([source_dir], [test_file], harness_dir)

        assert (drive_path / "test_example.py").exists()
        assert (drive_path / "test_example.py").read_text() == "def test_ok(): pass"

        transport.disconnect()

    def test_flash_stage_sends_autoreload_disable(
        self, tmp_path: Path,
    ) -> None:
        """stage() in flash mode should send autoreload disable via REPL."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
        transport.connect()
        port.writes.clear()

        transport.stage([source_dir], [], harness_dir)

        # Should have sent autoreload disable command.
        written_data = b"".join(port.writes)
        assert b"autoreload" in written_data
        assert b"False" in written_data

        transport.disconnect()

    def test_flash_disconnect_restores_autoreload(
        self, tmp_path: Path,
    ) -> None:
        """disconnect() in flash mode should re-enable autoreload."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                _RAW_REPL_PROMPT,   # _enter_raw_repl in disconnect
                _OK_RESPONSE,       # autoreload restore (disconnect)
            ],
        )

        transport = self._make_flash_transport(
            port, str(tmp_path / "CIRCUITPY"),
        )
        transport.connect()
        port.writes.clear()

        transport.disconnect()

        # Should have sent autoreload = True and supervisor.reload().
        written_data = b"".join(port.writes)
        assert b"autoreload" in written_data
        assert b"True" in written_data

    def test_flash_disconnect_restores_autoreload_after_reset(
        self, tmp_path: Path,
    ) -> None:
        """disconnect() after reset() should re-enter raw REPL and restore."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                _RAW_REPL_PROMPT,   # _enter_raw_repl in disconnect
                _OK_RESPONSE,       # autoreload restore (disconnect)
            ],
        )

        transport = self._make_flash_transport(
            port, str(tmp_path / "CIRCUITPY"),
        )
        transport.connect()

        # Simulate what _run_tests_on_device does: reset then disconnect.
        transport.reset()
        port.writes.clear()

        transport.disconnect()

        # Should have re-entered raw REPL (Ctrl-C×2, Ctrl-A) and
        # sent autoreload = True.
        written_data = b"".join(port.writes)
        assert _CTRL_C in port.writes
        assert _CTRL_A in port.writes
        assert b"autoreload" in written_data
        assert b"True" in written_data

    def test_ram_disconnect_does_not_send_autoreload(self) -> None:
        """disconnect() in ram mode should restore board but skip autoreload."""
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT,   # connect
                _RAW_REPL_PROMPT,   # _enter_raw_repl in disconnect
            ],
        )

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="ram",
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()
        port.writes.clear()

        transport.disconnect()

        written_data = b"".join(port.writes)
        # Should NOT send autoreload commands in ram mode.
        assert b"autoreload" not in written_data
        # Should still send Ctrl-B (exit raw REPL) and Ctrl-D (soft reboot).
        from chumicro_deploy.circuitpython_transport import _CTRL_B
        assert _CTRL_B in port.writes
        assert _CTRL_D in port.writes

    def test_flash_stage_is_idempotent_across_calls(
        self, tmp_path: Path,
    ) -> None:
        """Repeated stage() calls should produce the same drive state."""
        drive_path = tmp_path / "CIRCUITPY"
        drive_path.mkdir()

        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_timing"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        test_file_one = tmp_path / "test_one.py"
        test_file_one.write_text("def test_one(): pass")
        test_file_two = tmp_path / "test_two.py"
        test_file_two.write_text("def test_two(): pass")

        # Responses: connect, autoreload disable (stage 1),
        # autoreload disable (stage 2),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
        transport.connect()

        # First stage — libs + test_one.
        transport.stage([source_dir], [test_file_one], harness_dir)
        assert (drive_path / "lib" / "chumicro_timing" / "__init__.py").exists()
        assert (drive_path / "test_one.py").exists()

        # Second stage with test_two — rsync replaces root test files
        # and keeps libs intact (checksum match = no rewrite).
        transport.stage([source_dir], [test_file_two], harness_dir)
        assert (drive_path / "test_two.py").exists()
        # test_one should be gone (--delete removes stale files).
        assert not (drive_path / "test_one.py").exists()
        # Library content is unchanged.
        lib_init = drive_path / "lib" / "chumicro_timing" / "__init__.py"
        assert lib_init.read_text() == "# init"

        transport.disconnect()

    def test_flash_stage_excludes_pycache(
        self, tmp_path: Path,
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

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        lib_dir = drive_path / "lib"
        assert (lib_dir / "chumicro_timing" / "__init__.py").exists()
        assert (lib_dir / "chumicro_timing" / "ticks.py").exists()
        assert not (lib_dir / "chumicro_timing" / "__pycache__").exists()

        transport.disconnect()

    def test_flash_stage_overwrites_existing_package(
        self, tmp_path: Path,
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
        (package_dir / "__init__.py").write_text("# new")

        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        transport = self._make_flash_transport(port, str(drive_path))
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        # Existing files are overwritten with new content.
        assert (lib_dir / "__init__.py").read_text() == "# new"
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            serial_port_factory=factory,
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


class TestFindCircuitpyDrive:
    """Tests for find_circuitpy_drive auto-detection."""

    def test_returns_none_when_no_drive_found(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should return None when no known mount point exists."""
        original_is_dir = Path.is_dir

        def patched_is_dir(self_path: Path) -> bool:
            if "CIRCUITPY" in str(self_path):
                return False
            return original_is_dir(self_path)

        monkeypatch.setattr(Path, "is_dir", patched_is_dir)
        assert find_circuitpy_drive() is None

    def test_finds_macos_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should find a CIRCUITPY volume at /Volumes/ style path."""
        fake_volumes = tmp_path / "Volumes"
        fake_drive = fake_volumes / "CIRCUITPY"
        fake_drive.mkdir(parents=True)

        # Patch Path.is_dir to recognize our fake path.
        original_is_dir = Path.is_dir

        def patched_is_dir(self_path: Path) -> bool:
            if str(self_path) == "/Volumes/CIRCUITPY":
                return True
            return original_is_dir(self_path)

        monkeypatch.setattr(Path, "is_dir", patched_is_dir)
        result = find_circuitpy_drive()
        assert result == "/Volumes/CIRCUITPY"

    def test_finds_linux_media_mount(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should find a CIRCUITPY volume at /media/<user>/ style path."""
        monkeypatch.setenv("USER", "testuser")

        original_is_dir = Path.is_dir

        def patched_is_dir(self_path: Path) -> bool:
            path_str = str(self_path)
            if path_str == "/Volumes/CIRCUITPY":
                return False  # Block macOS path.
            if path_str == "/media/testuser/CIRCUITPY":
                return True
            return original_is_dir(self_path)

        monkeypatch.setattr(Path, "is_dir", patched_is_dir)
        result = find_circuitpy_drive()
        assert result == "/media/testuser/CIRCUITPY"

    def test_falls_back_to_getpass_when_user_env_unset(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """USER env unset should still produce a populated /media path
        via getpass.getuser, not /media//CIRCUITPY."""
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport.getpass.getuser",
            lambda: "fallback_user",
        )

        original_is_dir = Path.is_dir
        observed_candidates: list[str] = []

        def patched_is_dir(self_path: Path) -> bool:
            path_str = str(self_path)
            if path_str == "/Volumes/CIRCUITPY":
                observed_candidates.append(path_str)
                return False
            if path_str == "/media/fallback_user/CIRCUITPY":
                observed_candidates.append(path_str)
                return True
            return original_is_dir(self_path)

        monkeypatch.setattr(Path, "is_dir", patched_is_dir)
        result = find_circuitpy_drive()
        assert result == "/media/fallback_user/CIRCUITPY"
        # Ensure we never tried a malformed `/media//CIRCUITPY` path.
        assert "/media//CIRCUITPY" not in observed_candidates

    def test_skips_linux_paths_when_username_unresolvable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No USER and no passwd entry should fall through to /Volumes
        only — never produce /media//CIRCUITPY."""
        monkeypatch.delenv("USER", raising=False)

        def boom() -> str:
            raise KeyError("no passwd entry")

        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport.getpass.getuser",
            boom,
        )

        original_is_dir = Path.is_dir
        observed_candidates: list[str] = []

        def patched_is_dir(self_path: Path) -> bool:
            path_str = str(self_path)
            if "CIRCUITPY" in path_str:
                observed_candidates.append(path_str)
                return False
            return original_is_dir(self_path)

        monkeypatch.setattr(Path, "is_dir", patched_is_dir)
        result = find_circuitpy_drive()
        assert result is None
        # Only /Volumes/CIRCUITPY should have been probed; no /media/.
        assert observed_candidates == ["/Volumes/CIRCUITPY"]

    def test_flash_stage_auto_detects_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """stage() in flash mode should auto-detect the drive path."""
        fake_drive = tmp_path / "CIRCUITPY"
        fake_drive.mkdir()

        # Make find_circuitpy_drive return our fake path.
        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport"
            ".find_circuitpy_drive",
            lambda: str(fake_drive),
        )

        source_dir = tmp_path / "src"
        source_dir.mkdir()
        harness_dir = tmp_path / "harness"
        harness_dir.mkdir()

        # Responses: connect, autoreload disable (stage),
        # _enter_raw_repl + autoreload restore (disconnect).
        port = FakeSerialPort(
            read_responses=[
                _RAW_REPL_PROMPT, _OK_RESPONSE,
                _RAW_REPL_PROMPT, _OK_RESPONSE,
            ],
        )

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()
        transport.stage([source_dir], [], harness_dir)

        # Should have used the auto-detected path — lib/ created there.
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
        # connect() was never called — _port stays None.
        assert transport.reset_into_bootloader() is False

    def test_send_exception_swallowed_returns_true(self) -> None:
        # No _OK_RESPONSE supplied — _send_repl_command will raise when
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
        dance and emits no warnings — the USB link is gone on purpose.
        """
        # Read sequence: connect (prompt) + reset OK + (no more reads
        # because disconnect now skips _enter_raw_repl + autoreload).
        port = FakeSerialPort(read_responses=[_RAW_REPL_PROMPT, _OK_RESPONSE])
        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",  # exercises autoreload-restore code path
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
        # reset_into_bootloader nulled the port itself; disconnect
        # had nothing left to restore or close and the transport is
        # reusable via a fresh connect() once the board is back.
        assert transport._port is None


class TestDeployFiles:
    """Tests for CircuitpythonTransport.deploy_files (Slice 1d)."""

    def _connect(
        self,
        *,
        mode: str = "flash",
        drive_path: str | None = None,
        extra_responses: list[bytes] | None = None,
    ) -> tuple[CircuitpythonTransport, FakeSerialPort]:
        # Responses for: connect (prompt) + re-enter raw REPL (prompt) +
        # autoreload-off command (OK) + entrypoint exec (OK with output).
        # Tests supply the extra OK responses for additional commands.
        reads = [_RAW_REPL_PROMPT]
        if extra_responses:
            reads.extend(extra_responses)
        port = FakeSerialPort(read_responses=reads)

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode=mode,
            circuitpy_drive_path=drive_path,
            serial_port_factory=factory,
            time=FakeTime(),
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
        self, tmp_path: Path
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
            drive_path=str(drive), extra_responses=extra
        )
        output = transport.deploy_files(
            {"/code.py": b"print('hi')", "/lib/util.py": b"X = 1"},
            "/code.py",
        )
        assert "hello" in output
        assert (drive / "code.py").read_bytes() == b"print('hi')"
        assert (drive / "lib" / "util.py").read_bytes() == b"X = 1"

    def test_autoreload_disabled_before_writes(self, tmp_path: Path) -> None:
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
            drive_path=str(drive), extra_responses=extra
        )
        transport.deploy_files({"/code.py": b"pass"}, "/code.py")
        combined_writes = b"".join(port.writes).decode("utf-8", errors="replace")
        assert "supervisor.runtime.autoreload = False" in combined_writes

    def test_on_file_staged_invoked_per_file_sorted(self, tmp_path: Path) -> None:
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
            drive_path=str(drive), extra_responses=extra
        )
        staged: list[str] = []
        transport.deploy_files(
            {"/lib/util.py": b"X = 1", "/code.py": b"pass"},
            "/code.py",
            on_file_staged=staged.append,
        )
        assert staged == ["/code.py", "/lib/util.py"]

    def test_on_execute_line_emits_per_line(self, tmp_path: Path) -> None:
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
            drive_path=str(drive), extra_responses=extra
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
            "chumicro_deploy.circuitpython_transport.find_circuitpy_drive",
            lambda: None,
        )
        transport, _ = self._connect(drive_path=None)
        with pytest.raises(CircuitpythonTransportError, match="CIRCUITPY drive not found"):
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
            circuitpy_drive_path=str(tmp_path),
            serial_port_factory=lambda **_: FakeSerialPort(),
            time=FakeTime(),
        )
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            transport.deploy_files({"/code.py": b"pass"}, "/code.py")

    def test_stale_pre_reboot_banner_is_discarded(
        self, tmp_path: Path
    ) -> None:
        """Pre-reboot stale output must not leak into the capture.

        Reproduces the Pi Pico W "one-cycle-delayed capture" failure
        mode: host opens the port, drain doesn't fully clear CP's
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
            drive_path=str(drive), extra_responses=extra
        )
        output = transport.deploy_files(
            {"/code.py": b"print('fresh')"}, "/code.py",
        )
        assert "fresh-output" in output
        assert "old-output" not in output
        assert "ZeroDivisionError" not in output

    def test_waits_for_board_to_see_new_entrypoint(
        self, tmp_path: Path
    ) -> None:
        """USB-MSC write visibility to CP is polled, not assumed.

        On a slow controller the first ``os.stat`` can still report
        the previous file's size; the transport retries until the
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
            drive_path=str(drive), extra_responses=extra
        )
        output = transport.deploy_files(
            {"/code.py": new_contents}, "/code.py",
        )
        assert "fresh-output" in output

    def test_raises_if_board_never_sees_new_entrypoint(
        self, tmp_path: Path
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
            drive_path=str(drive), extra_responses=extra
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

        def factory(**kwargs):
            return port

        transport = CircuitpythonTransport(
            "/dev/ttyUSB0",
            mode="flash",
            circuitpy_drive_path=drive_path,
            serial_port_factory=factory,
            time=FakeTime(),
        )
        transport.connect()
        return transport, port

    def test_skips_verification_when_boot_out_missing(
        self, tmp_path: Path,
    ) -> None:
        """No boot_out.txt -> no probe roundtrip, drive path unchanged."""
        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        transport, _ = self._make_transport(
            drive_path=str(drive),
            reads=[_RAW_REPL_PROMPT],  # connect only — no probe expected
        )
        assert transport._verify_drive_for_board(drive) == drive

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

    def test_auto_corrects_to_sibling_mount_on_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Wrong drive + a sibling mount that matches -> corrected path + warning."""
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
            "chumicro_deploy.circuitpython_transport"
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
        assert "auto-correcting" in captured.out
        assert "S2Mini" in captured.out

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
            "chumicro_deploy.circuitpython_transport"
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
            CircuitpythonTransportError, match="devices.yml",
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

    def test_read_boot_out_machine_extracts_suffix(
        self, tmp_path: Path,
    ) -> None:
        """``on DATE; MACHINE`` suffix is returned; malformed files -> None."""
        from chumicro_deploy.circuitpython_transport import (
            _read_boot_out_machine,
        )

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0 on 2026-01-02; Foo Board with xyz\n"
            "Board ID:foo\n",
            encoding="utf-8",
        )
        assert _read_boot_out_machine(drive) == "Foo Board with xyz"

        # Missing file
        empty = tmp_path / "OTHER"
        empty.mkdir()
        assert _read_boot_out_machine(empty) is None

        # Malformed (no semicolon)
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "boot_out.txt").write_text("weird line\n", encoding="utf-8")
        assert _read_boot_out_machine(bad) is None

    def test_find_circuitpy_drive_for_machine_scans_mounts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scans mounts and returns the first one whose machine matches."""
        from chumicro_deploy.circuitpython_transport import (
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
            "chumicro_deploy.circuitpython_transport"
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
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Two identical-machine boards → UID disambiguates; machine alone can't.

        Regression guard for the "two identical boards connected at
        once" case: both drives report the same ``_machine`` string,
        but ``UID:`` in ``boot_out.txt`` (and ``microcontroller.cpu.uid``
        over REPL) is unique.  The verifier must pick the UID-matching
        mount, even though the configured drive's machine-string
        already matches the probe.
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
            "chumicro_deploy.circuitpython_transport"
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
        captured = capsys.readouterr()
        assert "UID" in captured.out

    def test_machine_fallback_when_probe_has_no_uid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Old firmware → probe has no uid → machine-string fallback kicks in."""
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
            "chumicro_deploy.circuitpython_transport"
            "._circuitpy_volume_candidates",
            lambda: [wrong, right],
        )
        transport, _ = self._make_transport(
            drive_path=str(wrong),
            reads=[
                _RAW_REPL_PROMPT,
                # No uid in the probe response — machine fallback applies.
                self._probe_response("S2Mini with ESP32S2-S2FN4R2"),
            ],
        )
        assert transport._verify_drive_for_board(wrong) == right

    def test_returns_unchanged_when_uid_matches(
        self, tmp_path: Path,
    ) -> None:
        """UID on drive matches probe UID → no correction, no warning."""
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

    def test_read_boot_out_uid_extracts_uid_line(
        self, tmp_path: Path,
    ) -> None:
        """``UID:`` line is extracted and normalised to uppercase."""
        from chumicro_deploy.circuitpython_transport import (
            _read_boot_out_uid,
        )

        drive = tmp_path / "CIRCUITPY"
        drive.mkdir()
        (drive / "boot_out.txt").write_text(
            self._boot_out("S2Mini with ESP32S2-S2FN4R2", uid="487f301f0224"),
            encoding="utf-8",
        )
        assert _read_boot_out_uid(drive) == "487F301F0224"

        # Missing file
        empty = tmp_path / "OTHER"
        empty.mkdir()
        assert _read_boot_out_uid(empty) is None

        # File without UID line
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "boot_out.txt").write_text(
            "Adafruit CircuitPython 10.2.0 on 2026-01-02; Foo Board\n"
            "Board ID:foo\n",
            encoding="utf-8",
        )
        assert _read_boot_out_uid(bad) is None

    def test_find_circuitpy_drive_for_uid_scans_mounts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scans mounts and matches by UID (case-insensitive)."""
        from chumicro_deploy.circuitpython_transport import (
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
        monkeypatch.setattr(
            "chumicro_deploy.circuitpython_transport"
            "._circuitpy_volume_candidates",
            lambda: [first, second],
        )
        # Lower-case input matches upper-case UID in boot_out.txt.
        assert find_circuitpy_drive_for_uid("bbbb2222") == str(second)
        assert find_circuitpy_drive_for_uid("") is None
        assert find_circuitpy_drive_for_uid("CCCC3333") is None
