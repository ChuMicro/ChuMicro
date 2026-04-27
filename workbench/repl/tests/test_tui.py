"""Tests for the interactive TUI loop."""

from __future__ import annotations

import contextlib
import io

import pytest
from chumicro_repl import interactive
from chumicro_repl.highlight import strip_ansi_sequences
from chumicro_repl.testing import FakeKeyboard, FakeSerialPort, FakeTime
from chumicro_repl.tui import run_loop

CTRL_C = b"\x03"
CTRL_D = b"\x04"
CTRL_X = b"\x18"


class TestRunLoopForwarding:
    """run_loop forwards keystrokes to the port and prints serial output."""

    def test_keystrokes_are_written_to_the_port(self):
        port = FakeSerialPort(read_chunks=[b">>> "])
        keyboard = FakeKeyboard([b"hi\r\n", CTRL_X])
        output = io.StringIO()
        result = run_loop(
            port, keyboard, output,
            time=FakeTime(),
        )
        assert result == 0
        # The first keystroke chunk was forwarded; the Ctrl-X chunk was not.
        assert b"hi\r\n" in port.writes
        assert CTRL_X not in b"".join(port.writes)

    def test_ctrl_c_is_forwarded_to_the_board(self):
        port = FakeSerialPort()
        keyboard = FakeKeyboard([CTRL_C, CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert CTRL_C in b"".join(port.writes)

    def test_ctrl_d_is_forwarded_to_the_board(self):
        port = FakeSerialPort()
        keyboard = FakeKeyboard([CTRL_D, CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert CTRL_D in b"".join(port.writes)

    def test_serial_output_appears_in_stdout(self):
        port = FakeSerialPort(read_chunks=[b"hello\n", b"world\n"])
        keyboard = FakeKeyboard([CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert "hello" in output.getvalue()
        assert "world" in output.getvalue()

    def test_traceback_is_highlighted(self):
        traceback_bytes = (
            b"Traceback (most recent call last):\n"
            b'  File "code.py", line 1, in <module>\n'
            b"ValueError: oops\n"
        )
        port = FakeSerialPort(read_chunks=[traceback_bytes])
        keyboard = FakeKeyboard([CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert "\x1b[" in output.getvalue()
        assert "Traceback" in strip_ansi_sequences(output.getvalue())

    def test_keystroke_prefix_before_exit_key_is_forwarded(self):
        # When a single read_available batch contains "abc<CTRL-X>" the
        # prefix "abc" should still be sent to the board before the
        # loop exits.
        port = FakeSerialPort()
        keyboard = FakeKeyboard([b"abc" + CTRL_X])
        output = io.StringIO()
        result = run_loop(port, keyboard, output, time=FakeTime())
        assert result == 0
        assert b"abc" in b"".join(port.writes)
        assert CTRL_X not in b"".join(port.writes)


class TestUtf8SerialDecode:
    """run_loop decodes serial bytes UTF-8 safely across chunk boundaries."""

    def test_emoji_split_across_chunks(self):
        # 🙂 split across two reads; the second batch contains Ctrl-X to exit.
        port = FakeSerialPort(read_chunks=[b"\xf0\x9f", b"\x99\x82\n"])
        keyboard = FakeKeyboard([CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert "\U0001f642" in output.getvalue()


class TestInteractiveWrapper:
    """:func:`interactive` wires up the run_loop with injected dependencies."""

    def test_runs_with_injected_port_and_keyboard(self):
        port = FakeSerialPort(read_chunks=[b"banner\n"])
        captured: dict[str, object] = {}

        def factory(address: str, baudrate: int, timeout: float) -> FakeSerialPort:
            captured["address"] = address
            return port

        # input_stream is a BytesIO without fileno() — interactive() should
        # detect the absence of a real fd and skip raw-mode setup.
        input_stream = io.BytesIO()
        output = io.StringIO()

        # The default _StdinKeyboard reads from input_stream.read1(); BytesIO
        # supports read1, so feed scripted bytes and then EOF naturally
        # exits via the Ctrl-X path below.
        input_stream.write(CTRL_X)
        input_stream.seek(0)

        result = interactive(
            "/dev/cu.dev",
            input_stream=input_stream,
            output=output,
            time=FakeTime(),
            port_factory=factory,
        )
        assert result == 0
        assert port.closed
        assert captured["address"] == "/dev/cu.dev"

    def test_raw_mode_callable_runs_when_fd_is_real(self, tmp_path):
        # A real fd backs a temp file; the raw-mode hook should be called.
        port = FakeSerialPort(read_chunks=[])
        scripted_input = tmp_path / "stdin"
        scripted_input.write_bytes(CTRL_X)
        opened = scripted_input.open("rb")
        called: list[int] = []

        @contextlib.contextmanager
        def fake_raw_mode(fd: int):
            called.append(fd)
            yield

        result = interactive(
            "/dev/cu.dev",
            input_stream=opened,
            output=io.StringIO(),
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
            raw_mode_context=fake_raw_mode,
        )
        opened.close()
        assert result == 0
        assert len(called) == 1

    def test_invalid_device_raises(self):
        with pytest.raises(TypeError):
            interactive(object(), output=io.StringIO())  # type: ignore[arg-type]


class TestExitKeyForwarding:
    """Ctrl-X exits without being forwarded to the device."""

    def test_only_exit_key_in_chunk(self):
        port = FakeSerialPort()
        keyboard = FakeKeyboard([CTRL_X])
        result = run_loop(port, keyboard, io.StringIO(), time=FakeTime())
        assert result == 0
        assert port.writes == []


class TestStartupBannerAndNudge:
    """Banner is written before the loop; initial_send pokes the device."""

    def test_welcome_banner_written_before_first_serial_chunk(self):
        port = FakeSerialPort(read_chunks=[b"hello\n"])
        keyboard = FakeKeyboard([CTRL_X])
        output = io.StringIO()
        run_loop(
            port, keyboard, output,
            time=FakeTime(),
            welcome_banner="*** banner ***\r\n",
        )
        rendered = output.getvalue()
        assert rendered.startswith("*** banner ***\r\n")
        assert rendered.index("hello") > rendered.index("banner")

    def test_initial_send_writes_to_port_before_loop(self):
        # The nudge byte must be written before any keystroke or
        # serial-drain happens.
        port = FakeSerialPort()
        keyboard = FakeKeyboard([CTRL_X])
        run_loop(
            port, keyboard, io.StringIO(),
            time=FakeTime(),
            initial_send=b"\r",
        )
        assert port.writes[0] == b"\r"

    def test_no_banner_no_send_by_default(self):
        # Defaults are empty so the existing tests that don't pass
        # banner/nudge keep their pristine port.writes / output.
        port = FakeSerialPort()
        keyboard = FakeKeyboard([CTRL_X])
        output = io.StringIO()
        run_loop(port, keyboard, output, time=FakeTime())
        assert port.writes == []
        assert output.getvalue() == ""

    def test_interactive_supplies_banner_and_carriage_return(self):
        port = FakeSerialPort(read_chunks=[])
        scripted = io.BytesIO(CTRL_X)
        output = io.StringIO()
        from chumicro_deploy import Device
        from chumicro_repl import interactive

        device = Device(transport="circuitpython", address="/dev/cu.dev")
        result = interactive(
            device,
            input_stream=scripted,
            output=output,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        assert result == 0
        # Banner identifies the connection — transport, address, baudrate.
        rendered = output.getvalue()
        assert "chumicro-repl" in rendered
        assert "circuitpython" in rendered
        assert "/dev/cu.dev" in rendered
        assert "115200" in rendered
        # Keybinding hint shows the four keys the user cares about.
        assert "Ctrl-X" in rendered
        assert "Ctrl-C" in rendered
        assert "Ctrl-D" in rendered
        assert "Ctrl-E" in rendered
        # The CR nudge was sent to the port to elicit a fresh prompt.
        assert b"\r" in port.writes

    def test_interactive_with_bare_path_omits_transport_from_banner(self):
        # When device is a string (no Device construction), the banner
        # falls back to address + baudrate — no fabricated transport.
        port = FakeSerialPort(read_chunks=[])
        scripted = io.BytesIO(CTRL_X)
        output = io.StringIO()
        from chumicro_repl import interactive

        result = interactive(
            "/dev/cu.bare",
            input_stream=scripted,
            output=output,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        assert result == 0
        rendered = output.getvalue()
        assert "/dev/cu.bare" in rendered
        # No transport name fabricated.
        assert "circuitpython" not in rendered
        assert "micropython" not in rendered


class TestInteractiveLineWrapper:
    """``interactive_line`` wires the line-mode loop to a real port factory."""

    def test_runs_through_factory_and_closes_port(self, tmp_path) -> None:
        from chumicro_repl import interactive_line

        port = FakeSerialPort(read_chunks=[])
        captured: dict[str, object] = {}

        def factory(address: str, baudrate: int, timeout: float) -> FakeSerialPort:
            captured["address"] = address
            captured["baudrate"] = baudrate
            return port

        # Stub the line-mode loop so we don't need a real prompt_toolkit
        # session — the wrapper's job is the port plumbing + history root
        # plumbing, which the stub-driven assertions below exercise.
        from chumicro_repl import line_mode as line_mode_module

        def fake_run(
            real_port,
            *,
            output,
            address,
            history_root,
            welcome_banner,
            theme,
            time,
        ):
            captured["port_id"] = id(real_port)
            captured["history_root"] = history_root
            captured["banner"] = welcome_banner
            return 0

        old_runner = line_mode_module.run_line_mode
        line_mode_module.run_line_mode = fake_run  # type: ignore[assignment]
        try:
            result = interactive_line(
                "/dev/cu.dev",
                output=io.StringIO(),
                port_factory=factory,
                history_root=tmp_path,
                time=FakeTime(),
            )
        finally:
            line_mode_module.run_line_mode = old_runner  # type: ignore[assignment]
        assert result == 0
        assert port.closed
        assert captured["address"] == "/dev/cu.dev"
        assert captured["history_root"] == tmp_path
        # Welcome banner contains the address — the wrapper built it via
        # ``format_line_mode_banner``.
        assert "/dev/cu.dev" in str(captured["banner"])
