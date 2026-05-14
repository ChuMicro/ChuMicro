"""Tests for disconnect handling + auto-reconnect across all surfaces.

The fakes drive scripted ``OSError`` sequences through every public
entrypoint (``tail``, ``ReplSession``, ``run_loop``, ``interactive``)
to validate three things uniformly:

- a clean disconnect notice goes to ``output`` instead of a raw
  traceback bubbling out of the loop;
- the reconnect budget retries through the same factory and resumes
  on success;
- callers get a typed signal — :attr:`ExitCode.DISCONNECTED` from
  ``tail``, :class:`ReplSessionDisconnected` from
  ``ReplSession``, :attr:`ExitCode.DISCONNECTED` (``3``) from
  ``run_loop`` — that they can branch on without parsing strings.
"""

from __future__ import annotations

import io

import pytest
from chumicro_repl import (
    ExitCode,
    ReplSession,
    ReplSessionError,
    interactive,
    tail,
)
from chumicro_repl.highlight import strip_ansi_sequences
from chumicro_repl.session import ReplSessionDisconnected
from chumicro_repl.testing import FakeKeyboard, FakeSerialPort, FakeTime
from chumicro_repl.tui import run_loop

CTRL_X = b"\x18"
RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"


def _handshake_chunks() -> list[bytes | BaseException]:
    return [b"\r\n", RAW_REPL_PROMPT]


# ---------------------------------------------------------------------------
# tail() disconnect + reconnect
# ---------------------------------------------------------------------------

class TestTailDisconnect:
    """``tail()`` writes a clean notice and returns ``DISCONNECTED``."""

    def test_disconnect_with_no_reconnect_returns_exit_code(self):
        port = FakeSerialPort(read_chunks=[
            b"running\n",
            OSError("[Errno 6] Device not configured"),
        ])
        output = io.StringIO()
        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=output,
            time=FakeTime(),
            port_factory=port,
            reconnect_seconds=0.0,
        )
        assert result is ExitCode.DISCONNECTED
        rendered = strip_ansi_sequences(output.getvalue())
        assert "device disconnected" in rendered
        assert "Device not configured" in rendered
        assert port.closed

    def test_reconnect_succeeds_within_window(self):
        # First port emits some output, then disconnects.  Factory
        # hands out a second, live port on the next call.  Tail
        # should print the disconnect notice, reconnect, and keep
        # streaming.
        first_port = FakeSerialPort(read_chunks=[
            b"first\n",
            OSError("[Errno 6] Device not configured"),
        ])
        second_port = FakeSerialPort(read_chunks=[b"after-replug\n"])
        ports = iter([first_port, second_port])

        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=(captured := io.StringIO()),
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: next(ports),
            reconnect_seconds=5.0,
            reconnect_interval=0.1,
        )
        assert result is ExitCode.OK
        rendered = strip_ansi_sequences(captured.getvalue())
        assert "first" in rendered
        assert "device disconnected" in rendered
        assert "reconnected" in rendered
        assert "after-replug" in rendered
        assert first_port.closed
        assert second_port.closed

    def test_reconnect_budget_exhausted_returns_disconnected(self):
        # Factory keeps raising OSError — every reconnect attempt
        # fails.  After the budget runs out, tail returns
        # DISCONNECTED with a "giving up" notice.
        first_port = FakeSerialPort(read_chunks=[
            OSError("[Errno 6] Device not configured"),
        ])
        ports = [first_port]

        def factory(_address, _baudrate, _timeout):
            if ports:
                return ports.pop()
            raise OSError("port still missing")

        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=(captured := io.StringIO()),
            time=FakeTime(),
            port_factory=factory,
            reconnect_seconds=1.0,
            reconnect_interval=0.1,
        )
        assert result is ExitCode.DISCONNECTED
        rendered = strip_ansi_sequences(captured.getvalue())
        assert "giving up" in rendered

    def test_traceback_after_reconnect_still_detected(self):
        # First port disconnects, second port emits a traceback —
        # tail should reconnect, then return TRACEBACK_DETECTED.
        first_port = FakeSerialPort(read_chunks=[
            OSError("disconnected"),
        ])
        second_port = FakeSerialPort(read_chunks=[
            (
                b"Traceback (most recent call last):\n"
                b'  File "code.py", line 1, in <module>\n'
                b"ValueError: oops\n"
            ),
        ])
        ports = iter([first_port, second_port])

        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: next(ports),
            reconnect_seconds=2.0,
            reconnect_interval=0.1,
        )
        assert result is ExitCode.TRACEBACK_DETECTED


# ---------------------------------------------------------------------------
# ReplSession disconnect
# ---------------------------------------------------------------------------

class TestReplSessionDisconnect:
    """Disconnect mid-call surfaces as ``ReplSessionDisconnected``."""

    def test_disconnect_during_handshake(self):
        port = FakeSerialPort(read_chunks=[
            OSError("device unplugged before handshake"),
        ])
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=port,
        )
        with pytest.raises(ReplSessionDisconnected) as excinfo:
            with session:
                pytest.fail("entry should not succeed")
        assert "device disconnected" in str(excinfo.value)
        assert isinstance(excinfo.value.cause, OSError)
        assert isinstance(excinfo.value, ReplSessionError)
        assert port.closed

    def test_disconnect_during_exec(self):  # noqa: CHU001 — `exec` matches the public ReplSession.exec API
        chunks = [
            *_handshake_chunks(),
            OSError("cable popped out mid-exec"),
        ]
        port = FakeSerialPort(read_chunks=chunks)
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=port,
        )
        with session:
            with pytest.raises(ReplSessionDisconnected):
                session.exec("print('hi')", timeout=1.0)

    def test_disconnect_during_read_until(self):
        chunks = [
            *_handshake_chunks(),
            b"some\n",
            OSError("disconnected while waiting"),
        ]
        port = FakeSerialPort(read_chunks=chunks)
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=port,
        )
        with session:
            with pytest.raises(ReplSessionDisconnected):
                session.read_until("READY", timeout=2.0)

    def test_write_failure_during_handshake(self):
        # The board responds with the prompt but the write itself
        # fails — pyserial raises on the very first Ctrl-C send.
        port = FakeSerialPort(
            read_chunks=_handshake_chunks(),
            raise_on_write=OSError("write error"),
        )
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=port,
        )
        with pytest.raises(ReplSessionDisconnected):
            with session:
                pytest.fail("handshake write should fail")


# ---------------------------------------------------------------------------
# run_loop() disconnect + reconnect
# ---------------------------------------------------------------------------

class TestRunLoopDisconnect:
    """TUI loop drops cleanly on disconnect and reconnects when allowed."""

    def test_disconnect_no_reopen_returns_disconnected_exit_code(self):
        port = FakeSerialPort(read_chunks=[
            b"hello\n",
            OSError("device gone"),
        ])
        keyboard = FakeKeyboard()
        output = io.StringIO()
        result = run_loop(
            port, keyboard, output,
            time=FakeTime(),
        )
        assert result == int(ExitCode.DISCONNECTED)
        rendered = strip_ansi_sequences(output.getvalue())
        assert "device disconnected" in rendered

    def test_reconnect_succeeds_after_replug(self):
        first_port = FakeSerialPort(read_chunks=[
            b"hello\n",
            OSError("unplugged"),
        ])
        second_port = FakeSerialPort(read_chunks=[
            b"after-replug\n",
        ])
        ports = iter([second_port])

        # Four b"" / CTRL_X entries map to four keyboard reads:
        # (1) main loop iter 1 (drains "hello"),
        # (2) main loop iter 2 (triggers the disconnect read),
        # (3) reconnect helper's first iteration (lets reopen run),
        # (4) main loop iter 3 after reconnect (CTRL_X to exit).
        keyboard = FakeKeyboard([b"", b"", b"", CTRL_X])
        output = io.StringIO()
        result = run_loop(
            first_port,
            keyboard,
            output,
            time=FakeTime(),
            reopen=lambda: next(ports),
            reconnect_seconds=2.0,
            reconnect_interval=0.05,
        )
        assert result == 0
        rendered = strip_ansi_sequences(output.getvalue())
        assert "hello" in rendered
        assert "device disconnected" in rendered
        assert "reconnected" in rendered
        assert "after-replug" in rendered
        assert first_port.closed

    def test_user_exit_during_reconnect_returns_zero(self):
        # First run_loop keyboard read returns b"" (no exit yet),
        # the reconnect helper's first keyboard read returns
        # CTRL_X so the user gets out of the retry loop before any
        # reconnect attempt succeeds.  Loop returns 0, not
        # DISCONNECTED.
        port = FakeSerialPort(read_chunks=[OSError("gone")])
        keyboard = FakeKeyboard([b"", CTRL_X])

        def reopen():
            raise OSError("still gone")

        output = io.StringIO()
        result = run_loop(
            port,
            keyboard,
            output,
            time=FakeTime(),
            reopen=reopen,
            reconnect_seconds=10.0,
            reconnect_interval=0.05,
        )
        assert result == 0
        rendered = strip_ansi_sequences(output.getvalue())
        assert "device disconnected" in rendered
        # No "giving up" message — we exited via Ctrl-X.
        assert "giving up" not in rendered

    def test_reconnect_budget_exhausted(self):
        port = FakeSerialPort(read_chunks=[OSError("gone")])
        keyboard = FakeKeyboard()

        def reopen():
            raise OSError("still gone")

        output = io.StringIO()
        result = run_loop(
            port,
            keyboard,
            output,
            time=FakeTime(),
            reopen=reopen,
            reconnect_seconds=0.5,
            reconnect_interval=0.1,
        )
        assert result == int(ExitCode.DISCONNECTED)
        assert "giving up" in strip_ansi_sequences(output.getvalue())

    def test_initial_send_failure_triggers_reconnect(self):
        # The very first port.write(initial_send) fails.  With a
        # reopen closure the loop should reconnect immediately.
        # Reconnect helper's first keyboard read returns b"" so it
        # does not take the user-exit branch; main-loop's later
        # keyboard read returns CTRL_X to terminate the test.
        first_port = FakeSerialPort(
            raise_on_write=OSError("initial write failed"),
        )
        second_port = FakeSerialPort(read_chunks=[b"alive\n"])
        ports = iter([second_port])

        keyboard = FakeKeyboard([b"", CTRL_X])
        output = io.StringIO()
        result = run_loop(
            first_port,
            keyboard,
            output,
            time=FakeTime(),
            initial_send=b"\r",
            reopen=lambda: next(ports),
            reconnect_seconds=2.0,
            reconnect_interval=0.05,
        )
        assert result == 0
        rendered = strip_ansi_sequences(output.getvalue())
        assert "reconnected" in rendered
        assert "alive" in rendered


# ---------------------------------------------------------------------------
# interactive() default reconnect
# ---------------------------------------------------------------------------

class TestInteractiveReconnectDefaults:
    """``interactive()`` defaults to a finite-but-friendly reconnect window."""

    def test_disconnect_then_reconnect_via_default_factory(self):
        # First call returns a port that disconnects; second call
        # returns a port with one byte then Ctrl-X exits.
        first_port = FakeSerialPort(read_chunks=[OSError("unplugged")])
        second_port = FakeSerialPort(read_chunks=[b"reconnected\n"])
        ports = iter([first_port, second_port])

        scripted = io.BytesIO(CTRL_X)
        output = io.StringIO()
        result = interactive(
            "/dev/cu.fake",
            input_stream=scripted,
            output=output,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: next(ports),
            reconnect_seconds=2.0,
            reconnect_interval=0.05,
        )
        assert result == 0
        rendered = strip_ansi_sequences(output.getvalue())
        assert "device disconnected" in rendered
        assert "reconnected" in rendered

    def test_reconnect_zero_disables_retries(self):
        # With reconnect_seconds=0, the first OSError ends the loop.
        first_port = FakeSerialPort(read_chunks=[OSError("gone")])
        scripted = io.BytesIO()
        output = io.StringIO()
        result = interactive(
            "/dev/cu.fake",
            input_stream=scripted,
            output=output,
            time=FakeTime(),
            port_factory=first_port,
            reconnect_seconds=0.0,
        )
        assert result == int(ExitCode.DISCONNECTED)
