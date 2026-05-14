"""Tests for the ``chumicro-repl`` argparse-driven CLI."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from chumicro_repl import cli


class TestParser:
    """``build_parser`` wires up every flag the CLI promises."""

    def test_help_does_not_raise(self):
        parser = cli.build_parser()
        # SystemExit on -h is fine — we want to confirm the parser
        # builds at all, including all subparsers.
        with pytest.raises(SystemExit):
            parser.parse_args(["-h"])

    def test_address_only_default_mode(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--address", "/dev/cu.x"])
        assert args.address == "/dev/cu.x"
        assert args.baudrate == 115200
        assert args.tail is None
        assert args.fail_on_traceback is True
        assert args.mode == "passthrough"

    def test_address_is_required(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_tail_flag_is_float(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--address", "/dev/cu.x", "--tail", "2.5"])
        assert args.tail == pytest.approx(2.5)

    def test_no_fail_flag_inverts_default(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "--address", "/dev/cu.x",
            "--tail", "1",
            "--no-fail-on-traceback",
        ])
        assert args.fail_on_traceback is False


class TestMainDispatch:
    """``main`` routes to the tail or interactive subcommand."""

    def test_tail_mode_invokes_tail_function(self):
        # Patch the lazy-imported tail to return a known ExitCode.
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.OK
            result = cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
            ])
            assert result == 0
            fake_tail.assert_called_once()
            args, kwargs = fake_tail.call_args
            assert args[0] == "/dev/cu.x"
            assert args[1] == pytest.approx(0.1)
            assert kwargs["fail_on_traceback"] is True

    def test_tail_mode_returns_traceback_exit_code(self):
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.TRACEBACK_DETECTED
            result = cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
            ])
            assert result == int(ExitCode.TRACEBACK_DETECTED)

    def test_interactive_mode_invokes_interactive_function(self):
        with patch("chumicro_repl.tui.interactive") as fake_interactive:
            fake_interactive.return_value = 0
            result = cli.main(["--address", "/dev/cu.x"])
            assert result == 0
            fake_interactive.assert_called_once_with("/dev/cu.x")

    def test_line_mode_invokes_interactive_line(self):
        with patch("chumicro_repl.tui.interactive_line") as fake_line:
            fake_line.return_value = 0
            result = cli.main(["--address", "/dev/cu.x", "--mode", "line"])
            assert result == 0
            fake_line.assert_called_once_with("/dev/cu.x")

    def test_no_fail_propagates_to_tail(self):
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.OK
            cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
                "--no-fail-on-traceback",
            ])
            _, kwargs = fake_tail.call_args
            assert kwargs["fail_on_traceback"] is False
