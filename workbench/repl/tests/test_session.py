"""Tests for :class:`chumicro_repl.ReplSession`.

Drives a :class:`chumicro_repl.testing.FakeSerialPort` through the
raw-REPL handshake + exec / call / read_until primitives to validate
the protocol framing without real hardware.
"""

from __future__ import annotations

import re

import pytest
from chumicro_repl import ReplSession, ReplSessionError
from chumicro_repl.testing import FakeKeyboard, FakeSerialPort, FakeTime

RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"


def _handshake_chunks() -> list[bytes]:
    """Bytes the board emits in response to Ctrl-C / Ctrl-A handshake."""
    return [b"\r\n", RAW_REPL_PROMPT]


def _exec_response(stdout: bytes, stderr: bytes = b"") -> bytes:
    """Build the ``OK<stdout>\\x04<stderr>\\x04>`` framing in one chunk."""
    return b"OK" + stdout + b"\x04" + stderr + b"\x04>"


def _build_session(*, read_chunks):
    fake_port = FakeSerialPort(read_chunks=read_chunks)
    fake_time = FakeTime()
    session = ReplSession(
        "/dev/cu.fake",
        time=fake_time,
        port_factory=fake_port,
    )
    return session, fake_port, fake_time


class TestEnterAndExit:
    """Context-manager entry sends Ctrl-C/Ctrl-A; exit sends Ctrl-B."""

    def test_handshake_writes_interrupts_and_raw_repl_byte(self):
        session, port, _ = _build_session(read_chunks=_handshake_chunks())
        with session:
            assert port.writes[:2] == [b"\x03", b"\x03"]
            assert port.writes[2] == b"\x01"
        # Last write is Ctrl-B exiting raw REPL.
        assert port.writes[-1] == b"\x02"
        assert port.closed

    def test_failed_handshake_closes_port(self):
        # Board emits something other than the raw-REPL prompt.
        port = FakeSerialPort(read_chunks=[b"garbage\r\n>"])
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
            connect_timeout=0.05,
        )
        with pytest.raises(ReplSessionError):
            with session:
                pytest.fail("entry should not succeed")
        assert port.closed

    def test_use_outside_with_raises(self):
        port = FakeSerialPort(read_chunks=_handshake_chunks())
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        with pytest.raises(ReplSessionError):
            session.exec("print('hi')")


class TestExec:
    """:meth:`ReplSession.exec` parses the ``OK ... \\x04 ... \\x04>`` framing."""

    def test_returns_stdout_only(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"hello\n"),
        ]
        session, port, _ = _build_session(read_chunks=chunks)
        with session:
            assert session.exec("print('hello')") == "hello\n"
            sent = b"".join(port.writes)
            assert b"print('hello')" in sent
            assert b"\x04" in sent  # Ctrl-D terminates the exec input
        # After the with block: Ctrl-B is the final write.
        assert port.writes[-1] == b"\x02"
        assert port.closed

    def test_stderr_raises(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(
                stdout=b"",
                stderr=b'Traceback...\nValueError: bad\n',
            ),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            with pytest.raises(ReplSessionError) as excinfo:
                session.exec("raise ValueError('bad')")
        assert "ValueError" in excinfo.value.stderr

    def test_two_execs_in_one_chunk_each(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"first\n"),
            _exec_response(stdout=b"second\n"),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            assert session.exec("print('first')") == "first\n"
            assert session.exec("print('second')") == "second\n"

    def test_exec_response_split_across_chunks(self):
        # Split the response so OK and \x04 land in separate chunks.
        full_response = _exec_response(stdout=b"split\n")
        chunks = [
            *_handshake_chunks(),
            full_response[:3],
            full_response[3:6],
            full_response[6:],
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            assert session.exec("print('split')") == "split\n"

    def test_exec_response_missing_ok_marker_raises(self):
        chunks = [
            *_handshake_chunks(),
            b"WAT" + b"\x04" + b"\x04>",
        ]
        session, _, fake_time = _build_session(read_chunks=chunks)
        # The fake clock advances on _read_until_bytes timeouts.
        with pytest.raises(ReplSessionError):
            with session:
                session.exec("print('x')", timeout=0.05)


class TestCall:
    """:meth:`ReplSession.call` round-trips literal-eval values."""

    def test_basic_int_return(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"42\n"),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            result = session.call("compute")
        assert result == 42

    def test_string_return(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"'hello'\n"),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            result = session.call("greet")
        assert result == "hello"

    def test_dict_return(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"{'voltage': 3.3, 'temp': 21}\n"),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            result = session.call("read_sensor")
        assert result == {"voltage": 3.3, "temp": 21}

    def test_args_and_kwargs_rendered_in_call(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"None\n"),
        ]
        session, port, _ = _build_session(read_chunks=chunks)
        with session:
            session.call("update", 1, "two", flag=True)
        # The exec body must include the rendered repr of each arg.
        sent_text = b"".join(port.writes).decode("utf-8", errors="replace")
        assert "update(1, 'two', flag=True)" in sent_text

    def test_non_literal_return_raises(self):
        chunks = [
            *_handshake_chunks(),
            _exec_response(stdout=b"<object at 0x123>\n"),
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            with pytest.raises(ReplSessionError):
                session.call("get_object")


class TestReadUntil:
    """:meth:`ReplSession.read_until` reads decoded bytes for a regex."""

    def test_pattern_matches_inside_chunk(self):
        chunks = [
            *_handshake_chunks(),
            b"loading...\nREADY\nmore",
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            captured = session.read_until(r"READY", timeout=0.5)
        assert captured.endswith("READY")

    def test_pattern_split_across_chunks(self):
        chunks = [
            *_handshake_chunks(),
            b"line one\n",
            b"REA",
            b"DY tail",
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            captured = session.read_until(re.compile(r"READY"), timeout=0.5)
        assert captured.endswith("READY")

    def test_timeout_raises(self):
        chunks = [
            *_handshake_chunks(),
            b"unrelated\n",
        ]
        session, _, _ = _build_session(read_chunks=chunks)
        with session:
            with pytest.raises(ReplSessionError):
                session.read_until(r"NEVER_MATCHES", timeout=0.01)


class TestDeviceResolution:
    """The constructor accepts a Device object as well as a port path."""

    def test_device_object_address_is_used(self):
        from chumicro_deploy import Device

        device = Device(transport="circuitpython", address="/dev/cu.dev")
        port = FakeSerialPort(read_chunks=_handshake_chunks())
        captured: dict[str, object] = {}

        def factory(address, baudrate, timeout):
            captured["address"] = address
            captured["baudrate"] = baudrate
            return port

        session = ReplSession(
            device, time=FakeTime(), port_factory=factory,
        )
        with session:
            pass
        assert captured["address"] == "/dev/cu.dev"
        assert captured["baudrate"] == 115200

    def test_invalid_device_type_raises(self):
        with pytest.raises(TypeError):
            ReplSession(object())  # type: ignore[arg-type]


# Imported here so the module-level `from chumicro_repl.testing import ...`
# does not fail in `--collect-only` runs that try to inspect every test.
_ = FakeKeyboard  # silence the unused-import lint when tests don't need it
