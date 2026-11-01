"""``chumicro-repl`` command-line interface.

Thin wrapper over :func:`chumicro_repl.tui.interactive` and
:func:`chumicro_repl.tail`.  No logic beyond argument translation.
The CLI exists so the common cases ("connect to my board",
"tail my deploy") don't require a Python script.

Invoked via ``python -m chumicro_repl ...`` or, after installation,
the ``chumicro-repl`` console script.  Takes a bare serial-port
``--address``; richer device-selection surfaces are intentionally
not part of this CLI.
"""

from __future__ import annotations

import argparse
import sys
from functools import partial


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    """Attach the serial-port flags."""
    parser.add_argument(
        "--address",
        required=True,
        help=(
            "Serial port of the board, such as /dev/cu.usbmodem1101 on "
            "macOS or /dev/ttyACM0 on Linux."
        ),
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial speed in baud (default: 115200).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``chumicro-repl`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="chumicro-repl",
        description=(
            "Open the Python prompt (the REPL) of a CircuitPython or "
            "MicroPython board over USB serial, or print the board's "
            "output for a set time.  Tracebacks print in red.  "
            "Inside a ChuMicro workspace, chumicro-workspace repl opens "
            "the same session by the board's name in devices.yml."
        ),
        epilog=(
            "Keys in a session: Ctrl-X ends the session and leaves the "
            "board running.  Ctrl-C stops the program running on the "
            "board.  Ctrl-D at an empty prompt soft-reboots the board."
        ),
    )
    _add_device_args(parser)
    parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Print the board's output for SECONDS, then exit, in "
            "place of the interactive prompt.  A traceback, safe-mode, "
            "or hard-fault message ends it early with exit status 1."
        ),
    )
    parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help=(
            "--tail only.  Keep printing for the full SECONDS after a "
            "traceback and exit 0, to watch a board that crashes and "
            "restarts."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "How the prompt handles typing.  line edits each line on "
            "this computer, with history, Tab completion, and "
            ":commands (type :help).  passthrough sends every key to "
            "the board as it is pressed, which paste mode and "
            "raw-REPL tools need.  auto (default) picks line in a "
            "terminal and passthrough when input is piped.  Ignored "
            "with --tail."
        ),
    )
    return parser


def _resolve_mode(requested: str) -> str:
    """Resolve ``auto`` to ``line`` (TTY) or ``passthrough`` (piped stdin).

    ``line`` and ``passthrough`` pass through unchanged.  ``auto``
    inspects ``sys.stdin.isatty()`` and picks ``line`` only when stdin
    is a real terminal, because line mode's prompt_toolkit reader needs
    interactive input, so a piped or redirected stdin must fall back
    to byte passthrough.
    """
    if requested != "auto":
        return requested
    isatty = getattr(sys.stdin, "isatty", None)
    return "line" if (callable(isatty) and isatty()) else "passthrough"


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse *argv* and route to interactive / tail."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tail is not None:
        # Lazy-import so a plain ``--help`` doesn't pay tail's
        # pyserial dependency.  ExitCode is an IntEnum, so returning
        # it directly gives the shell the right exit status.
        from ._follow import tail  # noqa: PLC0415

        return int(tail(
            args.address,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
    from .recovery import coached_session_start  # noqa: PLC0415

    if _resolve_mode(args.mode) == "line":
        from .tui import interactive_line  # noqa: PLC0415

        connect = partial(interactive_line, args.address)
    else:
        from .tui import interactive  # noqa: PLC0415

        connect = partial(interactive, args.address)
    # Wrap the connect in the package's coaching loop so the common
    # first-run failures (port not found / busy / permission denied)
    # surface an actionable recovery plan instead of a bare pyserial
    # traceback.  A TTY session gets the full classify-render-retry
    # prompt; a piped or redirected stdin renders the plan once without
    # prompting (max_attempts=1), so a non-interactive run never blocks
    # on input.
    isatty = getattr(sys.stdin, "isatty", None)
    if callable(isatty) and isatty():
        return coached_session_start(connect)
    return coached_session_start(connect, max_attempts=1)
