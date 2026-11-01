"""``repl`` subcommand: interactive REPL and standalone tail mode.

For deploy-then-watch use `deploy <project> --tail`.  This command
never stages code to a board.  It owns only the interactive REPL
and standalone tail surfaces.
"""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _resolve_device,
    _resolve_workspace,
)


def _resolve_repl_mode(requested: str, *, stdin: object) -> str:
    """Pick the actual REPL mode given the user's *requested* value.

    *requested* is ``"auto"`` / ``"line"`` / ``"passthrough"``.  Auto
    picks ``line`` when stdin is a TTY (an interactive terminal) and
    ``passthrough`` otherwise.  Line mode requires interactive input
    (``prompt_toolkit`` reads from the terminal), so falling back to
    passthrough lets the same command work under CI / piped stdin.

    *stdin* is injected so tests can verify both branches without
    monkey-patching ``sys.stdin``.
    """
    if requested != "auto":
        return requested
    isatty = getattr(stdin, "isatty", None)
    return "line" if (callable(isatty) and isatty()) else "passthrough"


def _cmd_repl(args: argparse.Namespace) -> int:
    """Open an interactive REPL or tail the board's output.

    Two modes:

    * ``repl``: interactive REPL on the selected board.
    * ``repl --tail SECONDS``: capture the next *SECONDS* of REPL
      output, exit cleanly.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.tail is not None:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    mode = _resolve_repl_mode(args.mode, stdin=sys.stdin)
    if mode == "line":
        from chumicro_repl import interactive_line  # noqa: PLC0415

        def open_session() -> int:
            return interactive_line(device)
    else:
        from chumicro_repl import interactive  # noqa: PLC0415

        def open_session() -> int:
            return interactive(device)

    if args.non_interactive:
        return open_session()

    from chumicro_repl import coached_session_start  # noqa: PLC0415

    return coached_session_start(open_session)


def _add_repl_parser(subparsers: argparse._SubParsersAction) -> None:
    """``repl``: interactive REPL or standalone tail mode."""
    repl_parser = subparsers.add_parser(
        "repl",
        help="Open the board's Python prompt, or show its output for a while.",
        description=(
            "Open an interactive Python prompt on the board, the REPL.  "
            "Ctrl-X leaves it.  repl --tail SECONDS prints the board's "
            "output for that long and exits, with no prompt.  To deploy "
            "and then watch in one command, run deploy <name> --tail."
        ),
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Print the board's output for SECONDS, then exit, in place "
            "of the prompt.  The exit code is non-zero when a traceback "
            "appears."
        ),
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="With --tail, exit 0 even when the output shows a traceback.",
    )
    _add_non_interactive_arg(repl_parser)
    repl_parser.add_argument(
        "--mode",
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "How the prompt handles typing.  line edits each line on "
            "your computer before sending it, with history kept between "
            "sessions, Tab completion against the names on the board, "
            "and the :edit, :save, :load, and :snippets commands.  "
            "passthrough sends each key to the board as you press it, "
            "for paste mode and raw REPL.  auto, the default, picks "
            "line on a terminal and passthrough otherwise.  --tail "
            "ignores this option."
        ),
    )
    repl_parser.set_defaults(func=_cmd_repl)
