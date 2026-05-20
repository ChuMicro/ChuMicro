"""``chumicro-repl`` command-line interface.

Thin wrapper over :func:`chumicro_repl.tui.interactive` and
:func:`chumicro_repl.tail`.  No logic beyond argument translation —
the CLI exists so the common cases ("connect to my board",
"tail my deploy") don't require a Python script.

Invoked via ``python -m chumicro_repl ...`` or, after installation,
the ``chumicro-repl`` console script.  Takes a bare serial-port
``--address``; richer device-selection surfaces are intentionally
not part of this CLI.
"""

from __future__ import annotations

import argparse
import sys


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    """Attach the serial-port flags."""
    parser.add_argument(
        "--address",
        required=True,
        help="Serial port path (e.g. /dev/cu.usbmodem... or COM3).",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate (CircuitPython only; default 115200).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``chumicro-repl`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="chumicro-repl",
        description=(
            "Interactive serial REPL for CircuitPython and MicroPython "
            "boards, with traceback highlighting and a follow-mode "
            "tail() for deploy orchestration."
        ),
    )
    _add_device_args(parser)
    parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode: stream output for SECONDS, "
            "highlight tracebacks, exit non-zero on a detected "
            "traceback (unless --no-fail-on-traceback)."
        ),
    )
    parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help=(
            "Tail mode only: stream the full window even when a "
            "traceback or safe-mode banner is detected."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("line", "passthrough"),
        default="passthrough",
        help=(
            "Interactive input mode.  `passthrough` (default — today's "
            "TUI) forwards every keystroke to the device; `line` "
            "interposes a host-side line editor with persistent "
            "per-device history, cursor edit, and Ctrl-R reverse "
            "search.  The default flips to `line` once raw-REPL "
            "auto-detection lands."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point — parse *argv* and route to interactive / tail."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tail is not None:
        # Lazy-import so a plain ``--help`` doesn't pay tail's pyserial
        # dependency.  ExitCode is an IntEnum; returning it directly
        # gives the shell the right exit status.
        from ._follow import tail  # noqa: PLC0415

        return int(tail(
            args.address,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
    if args.mode == "line":
        from .tui import interactive_line  # noqa: PLC0415

        return interactive_line(args.address)
    from .tui import interactive  # noqa: PLC0415

    return interactive(args.address)
