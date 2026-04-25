"""Tests for :func:`chumicro_repl.tail`."""

from __future__ import annotations

import io

from chumicro_repl import ExitCode, tail
from chumicro_repl.highlight import strip_ansi_sequences
from chumicro_repl.testing import FakeSerialPort, FakeTime


def _build_factory(port: FakeSerialPort):
    """Return a port factory that hands back *port* without consulting args."""
    def factory(_address: str, _baudrate: int, _timeout: float) -> FakeSerialPort:
        return port
    return factory


CIRCUITPYTHON_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "code.py", line 1, in <module>\n'
    "RuntimeError: bad\n"
)


class TestExitCodes:
    """Each exit reason produces a distinct :class:`ExitCode`."""

    def test_clean_window_returns_ok(self):
        port = FakeSerialPort(read_chunks=[b"hello\n", b"world\n"])
        output = io.StringIO()
        time = FakeTime()
        result = tail(
            "/dev/cu.fake",
            seconds=0.05,
            output=output,
            time=time,
            port_factory=_build_factory(port),
        )
        assert result is ExitCode.OK
        # The window elapsed because the port stopped emitting and
        # FakeTime auto-advances on each sleep().
        assert "hello" in output.getvalue()
        assert "world" in output.getvalue()

    def test_traceback_ends_tail_early(self):
        port = FakeSerialPort(read_chunks=[
            b"running\n",
            CIRCUITPYTHON_TRACEBACK.encode("utf-8"),
        ])
        output = io.StringIO()
        time = FakeTime()
        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=output,
            time=time,
            port_factory=_build_factory(port),
        )
        assert result is ExitCode.TRACEBACK_DETECTED
        # The output captured the traceback before tail returned.
        assert "RuntimeError" in strip_ansi_sequences(output.getvalue())

    def test_no_fail_on_traceback_runs_full_window(self):
        port = FakeSerialPort(read_chunks=[
            CIRCUITPYTHON_TRACEBACK.encode("utf-8"),
        ])
        output = io.StringIO()
        time = FakeTime()
        result = tail(
            "/dev/cu.fake",
            seconds=0.05,
            output=output,
            fail_on_traceback=False,
            time=time,
            port_factory=_build_factory(port),
        )
        assert result is ExitCode.OK


class TestHighlightInline:
    """Tail emits ANSI escapes around detected patterns."""

    def test_traceback_is_wrapped_in_ansi(self):
        port = FakeSerialPort(read_chunks=[
            CIRCUITPYTHON_TRACEBACK.encode("utf-8"),
        ])
        output = io.StringIO()
        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=output,
            time=FakeTime(),
            port_factory=_build_factory(port),
        )
        assert result is ExitCode.TRACEBACK_DETECTED
        captured = output.getvalue()
        assert "\x1b[" in captured
        assert "Traceback" in strip_ansi_sequences(captured)


class TestStreamingDecode:
    """UTF-8 sequences split across reads do not corrupt the output."""

    def test_emoji_split_across_chunks(self):
        # 🙂 split into three reads: leading byte, two continuation bytes
        port = FakeSerialPort(read_chunks=[
            b"sample \xf0",
            b"\x9f",
            b"\x99\x82 done\n",
        ])
        output = io.StringIO()
        result = tail(
            "/dev/cu.fake",
            seconds=0.05,
            output=output,
            time=FakeTime(),
            port_factory=_build_factory(port),
        )
        assert result is ExitCode.OK
        assert "sample 🙂 done" in output.getvalue()


class TestPortLifecycle:
    """The port is always closed even when the tail exits early."""

    def test_close_on_traceback_path(self):
        port = FakeSerialPort(read_chunks=[
            CIRCUITPYTHON_TRACEBACK.encode("utf-8"),
        ])
        tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=_build_factory(port),
        )
        assert port.closed

    def test_close_on_clean_window(self):
        port = FakeSerialPort(read_chunks=[b"hello\n"])
        tail(
            "/dev/cu.fake",
            seconds=0.01,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=_build_factory(port),
        )
        assert port.closed


class TestDeviceResolution:
    """tail() accepts both Device instances and bare port path strings."""

    def test_device_object_address_used(self):
        from chumicro_deploy import Device

        device = Device(transport="micropython", address="/dev/cu.dev")
        port = FakeSerialPort(read_chunks=[b"hi\n"])
        captured: dict[str, object] = {}

        def factory(address: str, baudrate: int, timeout: float):
            captured["address"] = address
            captured["baudrate"] = baudrate
            return port

        tail(
            device,
            seconds=0.01,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=factory,
        )
        assert captured["address"] == "/dev/cu.dev"

    def test_invalid_device_raises(self):
        import pytest

        with pytest.raises(TypeError):
            tail(
                object(),  # type: ignore[arg-type]
                seconds=0.01,
                output=io.StringIO(),
                time=FakeTime(),
            )
