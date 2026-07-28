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
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "Interactive input mode.  `auto` (default) picks `line` on a "
            "TTY and `passthrough` when stdin is piped, since line mode "
            "needs interactive input.  `line` interposes a host-side line "
            "editor with persistent per-device history, cursor edit, and "
            "Ctrl-R reverse search.  `passthrough` forwards every "
            "keystroke to the device; use it for raw-REPL framing or "
            "paste-mode flows."
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
