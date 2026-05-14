"""Tests for line-mode REPL."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_repl.line_mode import (
    BUILTIN_COMMANDS,
    DEFAULT_HISTORY_ROOT,
    LineModeContext,
    _ExitLineMode,
    _forward_ctrl_c,
    _forward_ctrl_d,
    _split_command,
    build_line_mode_key_bindings,
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
    cleanly (mirrors prompt_toolkit's Ctrl-D behavior).
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


def _context(
    *, output: io.StringIO | None = None, port=None, **kwargs,
) -> LineModeContext:
    """Test helper — minimal `LineModeContext` for handler unit tests."""
    return LineModeContext(
        port=port or _stub_port(),  # type: ignore[arg-type]
        output=output if output is not None else io.StringIO(),
        **kwargs,
    )


class TestBuiltinCommands:
    def test_help_prints_registered_commands(self) -> None:
        context = _context()
        keep_running = BUILTIN_COMMANDS["help"](context, "")
        assert keep_running is True
        text = context.output.getvalue()
        assert ":help" in text
        assert ":quit" in text

    def test_quit_returns_false(self) -> None:
        context = _context()
        assert BUILTIN_COMMANDS["quit"](context, "") is False

    def test_rescan_clears_completion_cache(self) -> None:
        from chumicro_repl.completion import CompletionCache

        cache = CompletionCache()
        cache.put("", ["alpha", "beta"])
        assert cache.get("") == ("alpha", "beta")
        context = _context(completion_cache=cache)
        keep_running = BUILTIN_COMMANDS["rescan"](context, "")
        assert keep_running is True
        assert cache.get("") is None
        assert "completion cache cleared" in context.output.getvalue()

    def test_rescan_no_cache_explains(self) -> None:
        # Tests inject their own prompt_session — completion_cache is
        # left None.  :rescan should explain rather than NPE.
        context = _context()
        assert context.completion_cache is None
        keep_running = BUILTIN_COMMANDS["rescan"](context, "")
        assert keep_running is True
        assert "no port-backed completer" in context.output.getvalue()

    def test_help_lists_rescan(self) -> None:
        context = _context()
        BUILTIN_COMMANDS["help"](context, "")
        assert ":rescan" in context.output.getvalue()


class TestFormatLineModeBanner:
    def test_includes_address_and_exit_hint(self) -> None:
        banner = format_line_mode_banner(address="/dev/cu.fake")
        assert "/dev/cu.fake" in banner
        assert ":help" in banner
        assert ":quit" in banner

    def test_advertises_mpremote_style_key_bindings(self) -> None:
        """Users learn the keys from the banner — must list all three."""
        banner = format_line_mode_banner(address="/dev/cu.fake")
        assert "Ctrl-X" in banner
        assert "Ctrl-C" in banner
        assert "Ctrl-D" in banner
        assert "interrupt" in banner
        assert "soft-reboot" in banner


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
        """The `commands=` parameter lets external commands layer in."""
        port = _stub_port()
        session = _StubPromptSession([":custom_project extra args", ":quit"])
        called: list[tuple[LineModeContext, str]] = []

        def fake_handler(context: LineModeContext, rest: str) -> bool:
            called.append((context, rest))
            return True

        custom = dict(BUILTIN_COMMANDS, custom_project=fake_handler)
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
        assert len(called) == 1
        passed_context, passed_rest = called[0]
        assert passed_rest == "extra args"
        assert passed_context.port is port


class TestSaveLoadSnippets:
    """`:save` writes input history; `:load` replays it."""

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        snippets = tmp_path / "snippets"
        port = _stub_port()
        context = LineModeContext(
            port=port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=snippets,
        )
        # Simulate two prior input lines.
        context.input_history.extend([
            "import board",
            "led = board.LED",
        ])
        # Save under a name.
        BUILTIN_COMMANDS["save"](context, "my_setup")
        snippet_file = snippets / "my_setup.py"
        assert snippet_file.is_file()
        body = snippet_file.read_text()
        assert "import board" in body
        assert "led = board.LED" in body

        # Load into a fresh context — should ship lines to its port.
        fresh_port = _stub_port()
        fresh_context = LineModeContext(
            port=fresh_port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=snippets,
        )
        BUILTIN_COMMANDS["load"](fresh_context, "my_setup")
        recorded = b"".join(fresh_port.writes)  # type: ignore[attr-defined]
        assert b"import board\r\n" in recorded
        assert b"led = board.LED\r\n" in recorded
        # Loaded lines also added to the new session's history.
        assert "import board" in fresh_context.input_history

    def test_save_without_name_prints_usage(self, tmp_path: Path) -> None:
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        BUILTIN_COMMANDS["save"](context, "")
        assert "usage" in context.output.getvalue()

    def test_save_with_empty_history_does_nothing(self, tmp_path: Path) -> None:
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        BUILTIN_COMMANDS["save"](context, "empty")
        assert "nothing to save" in context.output.getvalue()
        # No file written.
        assert not (tmp_path / "snippets").exists() or not list(
            (tmp_path / "snippets").iterdir()
        )

    def test_save_caps_at_tail_lines(self, tmp_path: Path) -> None:
        """`:save` writes the most recent 10 lines, not all history."""
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        context.input_history.extend(f"line {index}" for index in range(20))
        BUILTIN_COMMANDS["save"](context, "tail")
        body = (tmp_path / "snippets" / "tail.py").read_text()
        # First 10 lines (0..9) shouldn't appear; lines 10..19 should.
        assert "line 0\n" not in body
        assert "line 19\n" in body
        assert body.count("\n") == 10  # 10 lines + trailing newline

    def test_load_unknown_snippet_warns(self, tmp_path: Path) -> None:
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        BUILTIN_COMMANDS["load"](context, "ghost")
        assert "not found" in context.output.getvalue()

    def test_load_without_name_prints_usage(self, tmp_path: Path) -> None:
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        BUILTIN_COMMANDS["load"](context, "")
        assert "usage" in context.output.getvalue()

    def test_snippets_lists_saved(self, tmp_path: Path) -> None:
        snippets = tmp_path / "snippets"
        snippets.mkdir()
        (snippets / "alpha.py").write_text("a = 1\n")
        (snippets / "beta.py").write_text("b = 2\n")
        # Non-.py file should be ignored.
        (snippets / "notes.txt").write_text("ignored\n")
        context = _context(output=io.StringIO(), snippets_root=snippets)
        BUILTIN_COMMANDS["snippets"](context, "")
        text = context.output.getvalue()
        assert "alpha" in text
        assert "beta" in text
        assert "notes" not in text

    def test_snippets_empty_dir(self, tmp_path: Path) -> None:
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        BUILTIN_COMMANDS["snippets"](context, "")
        assert "no snippets" in context.output.getvalue()

    def test_snippet_name_with_path_separator_sanitized(
        self, tmp_path: Path,
    ) -> None:
        """`:save foo/bar` shouldn't escape the snippet root."""
        context = _context(
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        context.input_history.append("x = 1")
        BUILTIN_COMMANDS["save"](context, "foo/bar")
        # Whatever name the sanitizer produced, the file lives under
        # the snippet root — not at /tmp/.../foo/bar.py.
        assert (tmp_path / "snippets").iterdir()
        for path in (tmp_path / "snippets").iterdir():
            assert path.parent == tmp_path / "snippets"


class TestEditCommand:
    """`:edit` ships editor-saved buffer to the device."""

    def test_edit_ships_lines_via_stub_editor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub `_open_editor` so the test never actually shells out.
        port = _stub_port()
        context = LineModeContext(
            port=port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
            editor="ignored",
        )

        def fake_open_editor(*, editor: str, file_path) -> int:
            file_path.write_text("a = 1\nb = 2\n")
            return 0

        from chumicro_repl import line_mode as line_mode_module
        monkeypatch.setattr(line_mode_module, "_open_editor", fake_open_editor)

        keep_running = BUILTIN_COMMANDS["edit"](context, "")
        assert keep_running is True
        recorded = b"".join(port.writes)  # type: ignore[attr-defined]
        assert b"a = 1\r\n" in recorded
        assert b"b = 2\r\n" in recorded
        assert "shipped 2 line(s)" in context.output.getvalue()

    def test_edit_nonzero_exit_skips_ship(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        port = _stub_port()
        context = LineModeContext(
            port=port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        from chumicro_repl import line_mode as line_mode_module
        monkeypatch.setattr(
            line_mode_module, "_open_editor",
            lambda *, editor, file_path: 1,
        )
        BUILTIN_COMMANDS["edit"](context, "")
        assert port.writes == []  # type: ignore[attr-defined]
        assert "editor exited 1" in context.output.getvalue()

    def test_edit_empty_buffer_no_ship(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        port = _stub_port()
        context = LineModeContext(
            port=port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )

        def fake_open_editor(*, editor: str, file_path) -> int:
            # Editor closed without writing anything.
            return 0

        from chumicro_repl import line_mode as line_mode_module
        monkeypatch.setattr(line_mode_module, "_open_editor", fake_open_editor)
        BUILTIN_COMMANDS["edit"](context, "")
        assert port.writes == []  # type: ignore[attr-defined]
        assert "buffer empty" in context.output.getvalue()

    def test_edit_seeds_with_recent_history(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The tempfile prefilled with recent input lets users polish without retyping."""
        port = _stub_port()
        context = LineModeContext(
            port=port,  # type: ignore[arg-type]
            output=io.StringIO(),
            snippets_root=tmp_path / "snippets",
        )
        context.input_history.extend(["seed_a", "seed_b"])
        captured: dict[str, str] = {}

        def fake_open_editor(*, editor: str, file_path) -> int:
            captured["seed"] = file_path.read_text()
            return 1  # exit non-zero so ship-loop is skipped

        from chumicro_repl import line_mode as line_mode_module
        monkeypatch.setattr(line_mode_module, "_open_editor", fake_open_editor)
        BUILTIN_COMMANDS["edit"](context, "")
        assert "seed_a" in captured["seed"]
        assert "seed_b" in captured["seed"]


class _FakeBuffer:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.reset_called = 0

    def reset(self) -> None:
        self.reset_called += 1
        self.text = ""


class _FakeApp:
    """Minimal prompt_toolkit ``Application`` stand-in for binding tests."""

    def __init__(self, buffer_text: str = "") -> None:
        self.current_buffer = _FakeBuffer(buffer_text)
        self.exit_calls: list[dict[str, object]] = []

    def exit(  # noqa: A003 — matches prompt_toolkit's method name
        self,
        result: object = None,
        exception: BaseException | None = None,
    ) -> None:
        self.exit_calls.append({"result": result, "exception": exception})


class _FakeEvent:
    def __init__(self, app: _FakeApp) -> None:
        self.app = app


def _binding_for(bindings: object, key: str) -> object:
    """Return the registered ``Binding`` for *key* (raises if missing)."""
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.keys import Keys
    target = {
        "c-c": Keys.ControlC,
        "c-d": Keys.ControlD,
        "c-x": Keys.ControlX,
    }[key]
    for binding in bindings.bindings:  # type: ignore[attr-defined]
        if binding.keys == (target,):
            return binding
    raise AssertionError(f"no binding registered for {key!r}")


class TestForwardCtrlBytes:
    """Standalone helpers — verify the byte-level contract first."""

    def test_forward_ctrl_c_writes_etx(self) -> None:
        port = _StubSerialPort()
        _forward_ctrl_c(port)  # type: ignore[arg-type]
        assert port.writes == [b"\x03"]

    def test_forward_ctrl_d_writes_eot(self) -> None:
        port = _StubSerialPort()
        _forward_ctrl_d(port)  # type: ignore[arg-type]
        assert port.writes == [b"\x04"]


class TestKeyBindings:
    """Key bindings forward Ctrl-bytes to the device, not the local prompt.

    Verifies the convention change: ``Ctrl-C`` used to exit line mode,
    leaving the user with no way to interrupt a runaway program.
    """

    def test_ctrl_c_forwards_to_device_and_clears_buffer(self) -> None:
        pytest.importorskip("prompt_toolkit")
        port = _StubSerialPort()
        bindings = build_line_mode_key_bindings(port)  # type: ignore[arg-type]
        binding = _binding_for(bindings, "c-c")
        app = _FakeApp(buffer_text="half-typed-line")
        event = _FakeEvent(app)
        binding.handler(event)  # type: ignore[attr-defined]
        assert port.writes == [b"\x03"], "Ctrl-C should send ETX to the device"
        assert app.current_buffer.reset_called == 1, "local buffer should clear"
        assert app.exit_calls == [{"result": "", "exception": None}]

    def test_ctrl_d_forwards_to_device(self) -> None:
        pytest.importorskip("prompt_toolkit")
        port = _StubSerialPort()
        bindings = build_line_mode_key_bindings(port)  # type: ignore[arg-type]
        binding = _binding_for(bindings, "c-d")
        app = _FakeApp(buffer_text="")
        event = _FakeEvent(app)
        binding.handler(event)  # type: ignore[attr-defined]
        assert port.writes == [b"\x04"], "Ctrl-D should send EOT to the device"
        assert app.exit_calls == [{"result": "", "exception": None}]

    def test_ctrl_x_raises_exit_sentinel_locally(self) -> None:
        pytest.importorskip("prompt_toolkit")
        port = _StubSerialPort()
        bindings = build_line_mode_key_bindings(port)  # type: ignore[arg-type]
        binding = _binding_for(bindings, "c-x")
        app = _FakeApp()
        event = _FakeEvent(app)
        binding.handler(event)  # type: ignore[attr-defined]
        # Nothing leaves the host — Ctrl-X is the local-exit key.
        assert port.writes == []
        assert len(app.exit_calls) == 1
        assert isinstance(app.exit_calls[0]["exception"], _ExitLineMode)


class TestRunLineModeExitPaths:
    """Loop handles the new ``_ExitLineMode`` sentinel from Ctrl-X."""

    def test_exit_line_mode_exception_yields_clean_exit(
        self, tmp_path: Path,
    ) -> None:
        class _CtrlXSession:
            def prompt(self, _prompt_text: str = "") -> str:
                raise _ExitLineMode

        port = _stub_port()
        output = io.StringIO()
        exit_code = run_line_mode(
            port,
            output=output,
            address="/dev/cu.fake",
            history_root=tmp_path,
            prompt_session=_CtrlXSession(),
            time=_FastTime(),  # type: ignore[arg-type]
        )
        assert exit_code == 0
        assert "bye" in output.getvalue()
        assert port.writes == []  # type: ignore[attr-defined]


class TestPromptSessionConstruction:
    """Real `prompt_toolkit.PromptSession` factory must build cleanly."""

    def test_real_session_has_history_attached(self, tmp_path: Path) -> None:
        pytest.importorskip("prompt_toolkit")
        from chumicro_repl.line_mode import _build_prompt_session
        from chumicro_repl.testing import FakeSerialPort, FakeTime

        session = _build_prompt_session(
            address="/dev/cu.fake",
            history_root=tmp_path,
            port=FakeSerialPort(read_chunks=[]),
            time=FakeTime(),
            cache=None,
        )
        # The underlying session carries a FileHistory with our path.
        from prompt_toolkit.history import FileHistory
        assert isinstance(session.history, FileHistory)
        # Path matches our convention.
        expected = history_path_for("/dev/cu.fake", root=tmp_path)
        assert Path(session.history.filename) == expected
        # Mpremote-style key bindings are wired in — without these the
        # user has no way to interrupt a runaway loop on the device.
        assert session.key_bindings is not None
        registered_keys = {
            binding.keys for binding in session.key_bindings.bindings
        }
        from prompt_toolkit.keys import Keys
        assert (Keys.ControlC,) in registered_keys
        assert (Keys.ControlD,) in registered_keys
        assert (Keys.ControlX,) in registered_keys
