"""Tests for line-mode REPL (Phase 7 Slice 1a)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_repl.line_mode import (
    BUILTIN_COMMANDS,
    DEFAULT_HISTORY_ROOT,
    _split_command,
    format_line_mode_banner,
    history_path_for,
    run_line_mode,
    sanitize_address,
)

if TYPE_CHECKING:
    from chumicro_repl._serial import SerialPort


class _StubSerialPort:
    """In-memory ``SerialPort`` that records writes + replays scripted output.

    Each scripted entry is the bytes the device "emits" in response
    to the *next* write.  The drain helper polls ``in_waiting``;
    when a queued chunk is non-empty we report it as a single drain.
    """

    def __init__(self, scripted_outputs: list[bytes] | None = None) -> None:
        self.writes: list[bytes] = []
        self._scripted = list(scripted_outputs or [])
        self._buffer = b""

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def read(self, size: int = 1) -> bytes:
        chunk = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return chunk

    def write(self, data: bytes, /) -> int | None:
        self.writes.append(data)
        # The next write triggers loading the next scripted response
        # into the buffer — drain reads it back out.
        if self._scripted:
            self._buffer += self._scripted.pop(0)
        return len(data)

    def close(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self._buffer = b""


class _StubPromptSession:
    """In-memory `prompt_toolkit.PromptSession` substitute.

    Each call to ``.prompt()`` returns the next scripted line; once
    the script is exhausted an EOFError raises so the loop exits
    cleanly (mirrors prompt_toolkit's Ctrl-D behaviour).
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def prompt(self, _prompt_text: str = "") -> str:
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


# Avoid wall-clock waits in the drain loop.
class _FastTime:
    def __init__(self) -> None:
        self._now = 0.0

    def monotonic(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += seconds


def _stub_port(scripts: list[bytes] | None = None) -> SerialPort:
    return _StubSerialPort(scripts)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSanitizeAddress:
    def test_strips_dev_path_separators(self) -> None:
        assert sanitize_address("/dev/cu.usbmodem1101") == "dev_cu_usbmodem1101"

    def test_keeps_alphanumerics_and_underscores(self) -> None:
        assert sanitize_address("COM3") == "COM3"
        assert sanitize_address("usb_ttyACM0") == "usb_ttyACM0"

    def test_collapses_runs_of_separators(self) -> None:
        assert sanitize_address("a//b//c") == "a_b_c"

    def test_empty_input_falls_back(self) -> None:
        assert sanitize_address("") == "unknown_device"
        assert sanitize_address("///") == "unknown_device"


class TestHistoryPathFor:
    def test_creates_per_device_subdir(self, tmp_path: Path) -> None:
        path = history_path_for("/dev/cu.usbmodem1101", root=tmp_path)
        assert path.parent.is_dir()
        assert path.parent.name == "dev_cu_usbmodem1101"
        assert path.name == "history.txt"

    def test_default_root_is_under_home(self) -> None:
        path = history_path_for("any-device")
        assert path.is_relative_to(DEFAULT_HISTORY_ROOT)


class TestSplitCommand:
    def test_command_only(self) -> None:
        assert _split_command(":help") == ("help", "")

    def test_command_with_argument(self) -> None:
        assert _split_command(":save my-snippet") == ("save", "my-snippet")

    def test_empty_after_prefix(self) -> None:
        assert _split_command(":") == ("", "")

    def test_multi_word_argument(self) -> None:
        assert _split_command(":quote one two three") == (
            "quote", "one two three",
        )


class TestBuiltinCommands:
    def test_help_prints_registered_commands(self) -> None:
        output = io.StringIO()
        keep_running = BUILTIN_COMMANDS["help"](":help", output)
        assert keep_running is True
        text = output.getvalue()
        assert ":help" in text
        assert ":quit" in text

    def test_quit_returns_false(self) -> None:
        output = io.StringIO()
        assert BUILTIN_COMMANDS["quit"](":quit", output) is False


class TestFormatLineModeBanner:
    def test_includes_address_and_exit_hint(self) -> None:
        banner = format_line_mode_banner(address="/dev/cu.fake")
        assert "/dev/cu.fake" in banner
        assert ":help" in banner
        assert ":quit" in banner


# ---------------------------------------------------------------------------
# Integration — run_line_mode against the stub port + stub session
# ---------------------------------------------------------------------------


class TestRunLineMode:
    def test_ships_lines_to_device(self, tmp_path: Path) -> None:
        port = _stub_port(scripts=[b">>> 5\r\n", b">>> "])
        session = _StubPromptSession(["print('hello')", "1 + 4"])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        # Each line got written with a trailing CRLF.
        recorded = b"".join(port.writes)  # type: ignore[attr-defined]
        assert b"print('hello')\r\n" in recorded
        assert b"1 + 4\r\n" in recorded

    def test_eof_at_empty_prompt_exits_clean(self, tmp_path: Path) -> None:
        """Empty scripted prompt session → EOFError → clean exit."""
        port = _stub_port()
        session = _StubPromptSession([])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        assert "bye" in output.getvalue()

    def test_quit_command_exits(self, tmp_path: Path) -> None:
        port = _stub_port()
        session = _StubPromptSession([":quit"])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        # The :quit handler wrote its own bye line.
        assert "bye" in output.getvalue()
        # No lines were forwarded to the device.
        assert port.writes == []  # type: ignore[attr-defined]

    def test_help_command_keeps_running(self, tmp_path: Path) -> None:
        port = _stub_port()
        session = _StubPromptSession([":help", ":quit"])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        text = output.getvalue()
        assert ":help" in text
        assert "list registered commands" in text

    def test_unknown_command_prints_hint(self, tmp_path: Path) -> None:
        port = _stub_port()
        session = _StubPromptSession([":bogus", ":quit"])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        text = output.getvalue()
        assert "unknown command" in text
        assert "Try :help" in text

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        """Empty input from prompt_session shouldn't reach the device."""
        port = _stub_port()
        session = _StubPromptSession(["", ":quit"])
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        assert port.writes == []  # type: ignore[attr-defined]

    def test_welcome_banner_prints_first(self, tmp_path: Path) -> None:
        port = _stub_port()
        session = _StubPromptSession([":quit"])
        output = io.StringIO()
        run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            welcome_banner="-- WELCOME --\n",
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        text = output.getvalue()
        assert text.startswith("-- WELCOME --\n")

    def test_serial_output_renders_to_output_stream(
        self, tmp_path: Path,
    ) -> None:
        """Whatever the device emits between prompts shows up in *output*."""
        port = _stub_port(scripts=[b">>> 5\r\n>>> "])
        session = _StubPromptSession(["1 + 4"])
        output = io.StringIO()
        run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        # The device's response made it into the rendered output.
        assert "5" in output.getvalue()

    def test_custom_command_table_overrides_builtins(
        self, tmp_path: Path,
    ) -> None:
        """The `commands=` parameter lets Slice 1b layer richer commands in."""
        port = _stub_port()
        session = _StubPromptSession([":save back-porch", ":quit"])
        called: list[str] = []

        def fake_save(line: str, output) -> bool:
            called.append(line)
            return True

        custom = dict(BUILTIN_COMMANDS, save=fake_save)
        output = io.StringIO()
        run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            commands=custom,
            prompt_session=session,
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert called == [":save back-porch"]


class TestPromptSessionConstruction:
    """Real `prompt_toolkit.PromptSession` factory must build cleanly."""

    def test_real_session_has_history_attached(self, tmp_path: Path) -> None:
        pytest.importorskip("prompt_toolkit")
        from chumicro_repl.line_mode import _build_prompt_session

        session = _build_prompt_session(
            address="/dev/cu.fake", history_root=tmp_path,
        )
        # The underlying session carries a FileHistory with our path.
        from prompt_toolkit.history import FileHistory
        assert isinstance(session.history, FileHistory)
        # Path matches our convention.
        expected = history_path_for("/dev/cu.fake", root=tmp_path)
        assert Path(session.history.filename) == expected
