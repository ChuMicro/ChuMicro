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
        help=(
            "Interactive REPL on the selected board, or tail its serial "
            "output.  To deploy then watch, use `deploy <project> --tail`."
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
            "Run in tail mode for SECONDS instead of the interactive "
            "TUI.  (To deploy then tail in one go, use "
            "`deploy <project> --tail`.)"
        ),
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="Tail mode only: do not exit non-zero on a detected traceback.",
    )
    _add_non_interactive_arg(repl_parser)
    repl_parser.add_argument(
        "--mode",
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "Interactive REPL mode.  `line` (the better-featured "
            "default for terminal sessions) ships a host-side line "
            "editor with persistent history, `:edit` editor handoff, "
            "`:save`/`:load`/`:snippets`, and Tab completion against "
            "the on-device namespace.  `passthrough` forwards "
            "keystrokes byte-by-byte (mpremote-style, needed for "
            "raw REPL framing or paste mode).  `auto` (default) "
            "picks `line` when stdin is a TTY and `passthrough` "
            "otherwise.  No effect with `--tail` (tail mode uses the "
            "follower, not the interactive TUI)."
        ),
    )
    repl_parser.set_defaults(func=_cmd_repl)
