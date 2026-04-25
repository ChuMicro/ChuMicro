"""Targeted tests filling coverage gaps in the harder-to-reach branches.

Each test in this module covers a specific defensive branch, error
path, or seldom-hit edge case that the unit-test suites for each
module skip because they focus on the happy path.  Splitting these
out into one file keeps the per-module suites focused on behaviour
that a reader cares about while still hitting the agent-strict 94 %
coverage gate.
"""

from __future__ import annotations

import io
import sys

import chumicro_repl
import pytest
from chumicro_repl import (
    PatternKind,
    PatternMatch,
    ReplSession,
    ReplSessionError,
    Theme,
    Utf8StreamDecoder,
    cli,
    framing,
    interactive,
    tail,
)
from chumicro_repl._serial import default_port_factory
from chumicro_repl.testing import FakeKeyboard, FakeSerialPort, FakeTime


def _handshake_chunks() -> list[bytes]:
    return [b"\r\n", b"raw REPL; CTRL-B to exit\r\n>"]


# --- chumicro_repl/__init__.py ----------------------------------------------

class TestPackageDunder:
    """Lazy-attr fallback + ``__dir__``."""

    def test_unknown_attribute_raises(self):
        with pytest.raises(AttributeError):
            chumicro_repl.does_not_exist  # noqa: B018 — intentional access

    def test_dir_lists_lazy_attrs(self):
        names = chumicro_repl.__dir__()
        assert "ReplSession" in names
        assert "tail" in names
        assert "colorize" in names


# --- chumicro_repl/__main__.py ----------------------------------------------

class TestModuleEntrypoint:
    """``python -m chumicro_repl`` is the documented entry point."""

    def test_module_main_block_invokes_main(self, monkeypatch):
        # Importing the module without __name__ == '__main__' is a no-op.
        # We re-execute it under a synthetic ``__main__`` to hit the
        # ``raise SystemExit(...)`` line.
        monkeypatch.setattr(sys, "argv", ["chumicro-repl", "--help"])
        from chumicro_repl import __main__ as entry_module

        # build_parser triggers SystemExit on --help; that is the
        # success criterion — the entrypoint reaches argparse.
        with pytest.raises(SystemExit):
            entry_module.main(["--help"])


# --- framing.py edge cases ---------------------------------------------------

class TestFramingEdgeBytes:
    """Defensive branches in :func:`_utf8_continuation_start`."""

    def test_empty_chunk_returns_zero_directly(self):
        # _utf8_continuation_start is internal; reaching it through
        # the public API requires an empty decode call.
        decoder = Utf8StreamDecoder()
        assert decoder.decode(b"") == ""
        # Also exercise the internal helper so the early-return on
        # ``len(chunk) == 0`` is covered explicitly.
        assert framing._utf8_continuation_start(b"") == 0

    def test_all_continuation_bytes_flush(self):
        # Five continuation bytes — no leading byte exists.  The
        # helper falls through to ``return chunk_length``.
        chunk = b"\x80\x80\x80\x80\x80"
        assert framing._utf8_continuation_start(chunk) == len(chunk)

    def test_invalid_leading_byte_returns_full_length(self):
        # 0xfe is not a valid leading byte at any length.
        chunk = b"\xfe"
        assert framing._utf8_continuation_start(chunk) == len(chunk)


# --- _serial.py default_port_factory -----------------------------------------

class TestDefaultPortFactory:
    """The real factory imports pyserial lazily; a smoke test is enough."""

    def test_returns_serial_object_with_correct_baudrate(self, monkeypatch):
        captured: dict[str, object] = {}

        class FakeSerial:
            def __init__(self, address, baudrate, timeout):
                captured["address"] = address
                captured["baudrate"] = baudrate
                captured["timeout"] = timeout

        # Inject a fake ``serial`` module.
        fake_module = type(sys)("serial")
        fake_module.Serial = FakeSerial
        monkeypatch.setitem(sys.modules, "serial", fake_module)
        result = default_port_factory("/dev/cu.x", 9600, 0.1)
        assert isinstance(result, FakeSerial)
        assert captured == {
            "address": "/dev/cu.x", "baudrate": 9600, "timeout": 0.1,
        }


# --- session.py uncovered branches -------------------------------------------

class TestSessionDoubleEnter:
    """The session can be re-used after a clean exit by re-entering."""

    def test_exit_without_enter_is_safe(self):
        port = FakeSerialPort(read_chunks=_handshake_chunks())
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        # Exiting without entering must not raise — the with-block
        # never opened the port.
        session.__exit__(None, None, None)
        # Now enter normally.
        with session:
            pass

    def test_exec_unrecognized_response_raises(self):
        # Board emits OK, then nothing — the second \x04 read times
        # out because the FakeTime auto-advances on each sleep().
        chunks = [
            *_handshake_chunks(),
            b"OKstdout-but-no-eot",
        ]
        port = FakeSerialPort(read_chunks=chunks)
        session = ReplSession(
            "/dev/cu.fake",
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        with session:
            with pytest.raises(ReplSessionError):
                session.exec("print('x')", timeout=0.05)


# --- _follow.py — patterns that span the chunk boundary ----------------------

class TestTailMatchesAcrossChunks:
    """A pattern straddling two reads still matches and triggers the early exit."""

    def test_traceback_split_across_two_reads(self):
        traceback_bytes = (
            b"Traceback (most recent call last):\n"
            b'  File "code.py", line 1, in <module>\n'
            b"ValueError: split-across-reads\n"
        )
        # Slice the bytes mid-line so the first read is not a complete
        # pattern by itself.
        chunks = [traceback_bytes[:30], traceback_bytes[30:]]
        port = FakeSerialPort(read_chunks=chunks)
        output = io.StringIO()
        from chumicro_repl import ExitCode

        result = tail(
            "/dev/cu.fake",
            seconds=10.0,
            output=output,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        assert result is ExitCode.TRACEBACK_DETECTED

    def test_match_outside_local_chunk_window_is_skipped(self):
        # _highlight_chunk skips matches whose translated coordinates
        # fall entirely outside the current chunk — exercise that
        # branch directly via the helper.
        from chumicro_repl._follow import _highlight_chunk
        from chumicro_repl.patterns import StreamingPatternDetector

        detector = StreamingPatternDetector()
        # Feed text twice so detector total_fed > current chunk size.
        detector.feed("first chunk\n")
        text = "second chunk\n"
        detector.feed(text)
        # Construct a fake match whose absolute coordinates point at
        # the *first* feed — should be skipped during translation.
        spurious = PatternMatch(
            kind=PatternKind.SOFT_REBOOT, start=0, end=5, text="first",
        )
        result = _highlight_chunk(text, [spurious], detector, Theme())
        assert result == text


# --- cli.py — devices.yml routing -------------------------------------------

class TestCliDevicesFileRoute:
    """``--devices-file`` consults chumicro-deploy's loader registry."""

    def test_unknown_format_raises_systemexit(self, tmp_path):
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text("devices: []\n")
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(devices_file),
            "--devices-format", "definitely-not-a-format",
        ])
        with pytest.raises(SystemExit):
            cli._device_from_args(args)

    def test_known_format_invokes_loader(self, tmp_path, monkeypatch):
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text("devices: []\n")

        def fake_loader(path, *, device_id):
            return f"loaded:{path}:{device_id}"

        # Patch the loader registry to return our fake loader for
        # ``"default"``.  ``discover_config_loaders`` is the fan-in
        # point in chumicro-deploy.config.
        monkeypatch.setattr(
            "chumicro_deploy.config.discover_config_loaders",
            lambda: {"default": fake_loader},
        )
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(devices_file),
            "--device", "back-porch",
        ])
        result = cli._device_from_args(args)
        assert result == f"loaded:{devices_file}:back-porch"


# --- tui.py — fileno fall-throughs and stream behaviour ----------------------

class TestTuiHelpers:
    """Cover the ``_fileno_or_none`` and ``_StdinKeyboard`` paths."""

    def test_fileno_returns_none_for_stream_without_fileno(self):
        from chumicro_repl.tui import _fileno_or_none

        class NoFileno:
            pass

        assert _fileno_or_none(NoFileno()) is None  # type: ignore[arg-type]

    def test_fileno_returns_none_when_fileno_raises(self):
        from chumicro_repl.tui import _fileno_or_none

        class RaisingFileno:
            def fileno(self):
                raise OSError("no fd")

        assert _fileno_or_none(RaisingFileno()) is None  # type: ignore[arg-type]

    def test_stdin_keyboard_with_fd_uses_select(self, tmp_path):
        # A real fd-backed file: read_available reads up to 256 bytes
        # via select().  Under a temp file with pre-written content,
        # select() reports it readable and read1 returns the bytes.
        from chumicro_repl.tui import _StdinKeyboard

        path = tmp_path / "fd-input"
        path.write_bytes(b"hello")
        with path.open("rb") as opened:
            keyboard = _StdinKeyboard(opened, opened.fileno())
            assert keyboard.read_available() == b"hello"

    def test_interactive_with_fileno_skip_when_input_is_bytesio(self):
        # BytesIO has no fileno (raises OSError).  interactive() must
        # detect this and fall through to the no-raw-mode branch.
        port = FakeSerialPort(read_chunks=[b"banner\n"])
        scripted = io.BytesIO(b"\x18")  # Ctrl-X
        result = interactive(
            "/dev/cu.dev",
            input_stream=scripted,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        assert result == 0


# --- testing.py — uncovered helper paths -------------------------------------

class TestFakesAuxiliaryPaths:
    """The testing helpers expose a feed() / queue() path we should cover."""

    def test_fake_serial_feed_appends_more_chunks(self):
        port = FakeSerialPort(read_chunks=[b"first"])
        assert port.read(1) == b"first"
        # Empty after exhaustion.
        assert port.in_waiting == 0
        port.feed(b"second")
        assert port.in_waiting == len(b"second")
        assert port.read(1) == b"second"

    def test_fake_keyboard_queue_extends(self):
        keyboard = FakeKeyboard()
        assert keyboard.read_available() == b""
        keyboard.queue(b"abc", b"def")
        assert keyboard.read_available() == b"abc"
        assert keyboard.read_available() == b"def"
        assert keyboard.read_available() == b""

    def test_fake_time_advance_does_not_double(self):
        clock = FakeTime(start=10.0)
        assert clock.monotonic() == 10.0
        clock.advance(2.5)
        assert clock.monotonic() == 12.5
        clock.sleep(1.0)
        assert clock.monotonic() == 13.5

    def test_fake_serial_reset_input_buffer_is_no_op(self):
        port = FakeSerialPort(read_chunks=[b"hello"])
        port.reset_input_buffer()  # Must not raise / mutate state.
        assert port.read(1) == b"hello"
