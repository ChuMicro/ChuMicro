"""Tests for CircuitpythonTransport — pyserial raw REPL transport."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_device_transport.circuitpython_transport import (
    _CTRL_A,
    _CTRL_C,
    _CTRL_D,
    _RAW_REPL_PROMPT,
    CircuitpythonTransport,
    CircuitpythonTransportError,
)


def _noop_sleep(_duration: float) -> None:
    """No-op sleep replacement to eliminate delays in tests."""


class FakeSerialPort:
    """Simulates a pyserial Serial port for transport testing.

    Records all writes and returns canned responses for reads.
    """

    def __init__(
        self,
        *,
        read_responses: list[bytes] | None = None,
        open_error: Exception | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self._read_responses = list(read_responses or [])
        self._read_index = 0
        self._open_error = open_error
        self._buffer = b""

    @property
    def in_waiting(self) -> int:
        """Return how many bytes are available to read."""
        if self._read_index < len(self._read_responses):
            return len(self._read_responses[self._read_index])
        return 0

    def read(self, size: int = 1) -> bytes:
        """Return the next canned response."""
        if self._read_index < len(self._read_responses):
            data = self._read_responses[self._read_index]
            self._read_index += 1
            return data
        return b""

    def write(self, data: bytes) -> int:
        """Record a write."""
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        """Mark the port as closed."""
        self.closed = True

    def reset_input_buffer(self) -> None:
        """No-op for fake."""


def _make_factory(port: FakeSerialPort):
    """Create a factory callable that returns the given fake port."""
    def factory(*, port_path=None, baudrate=None, timeout=None, **kwargs):
        if port._open_error:
            raise port._open_error
        return port
    return factory


def _make_raw_repl_port(execute_stdout: str = "", execute_stderr: str = ""):
    """Create a FakeSerialPort pre-loaded with connect + execute responses.

    Returns the port and a factory for it.
    """
    execute_response = (
        f"OK{execute_stdout}\x04{execute_stderr}\x04>"
    ).encode()
    port = FakeSerialPort(
        read_responses=[
            _RAW_REPL_PROMPT,  # connect response
            execute_response,   # execute response
        ],
    )

    def factory(*, port=port, **kwargs):
        return port

    return port, factory


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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            timeout=0.1,
            serial_port_factory=factory,
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
        )
        # Manually set staged sources to bypass stage check.
        transport._staged_sources = []

        with pytest.raises(
            CircuitpythonTransportError,
            match="connect",
        ):
            transport.execute("print('hello')")


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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
        )
        transport.reset()  # Should not raise.


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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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
            sleep=_noop_sleep,
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

