"""``repl`` subcommand — interactive REPL, tail mode, deploy-then-tail."""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.boot_shim import project_boot_source
from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _emit_failure_hints,
    _resolve_device,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.cli.deploy import _make_deploy_runner

#: Default tail-window duration (seconds) when ``repl <project>`` is
#: invoked without an explicit ``--tail SECONDS`` value.  Picked to
#: cover the common "deploy a heartbeat project, watch a few cycles
#: print, exit clean" inner-loop pattern; users with long boot
#: sequences can override.
_DEFAULT_REPL_TAIL_SECONDS: float = 30.0


def _resolve_repl_mode(requested: str, *, stdin: object) -> str:
    """Pick the actual REPL mode given the user's *requested* value.

    *requested* is ``"auto"`` / ``"line"`` / ``"passthrough"``.  Auto
    picks ``line`` when stdin is a TTY (an interactive terminal) and
    ``passthrough`` otherwise — line mode requires interactive input
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
    """Open an interactive REPL, tail output, or deploy-then-tail.

    Three modes:

    * ``repl`` — interactive REPL on the selected board.
    * ``repl --tail SECONDS`` — capture the next *SECONDS* of REPL
      output, exit cleanly.
    * ``repl <project> [--tail SECONDS]`` — deploy *project* to the
      board first, then tail.  Combines what used to be
      ``deploy <project> && repl --tail`` into one command.  When
      ``--tail`` is omitted with a positional, defaults to
      :data:`_DEFAULT_REPL_TAIL_SECONDS`.

    *project* accepts bare / slash / dotted forms — same shape as
    ``deploy``.  The deploy uses the workspace-runtime boot-shim
    layout (``project_boot_source``); for flat-layout deploys, run
    ``deploy`` and ``repl --tail`` separately.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.project is not None:
        resolved_name = _resolve_project_name(workspace, args.project)
        project_dir = workspace.project_dir(resolved_name)
        if not project_dir.is_dir():
            raise SystemExit(f"error: project {project_dir} not found")
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
        )
        print(f"repl: deploying {resolved_name} ...")
        deleted: list[str] = []
        deploy_result = _make_deploy_runner(
            device, non_interactive=args.non_interactive,
        ).deploy_diff(
            source,
            on_file_deleted=deleted.append,
        )
        for stale_path in deleted:
            print(f"repl: removed stale {stale_path}")
        if deploy_result.execute_output:
            print(deploy_result.execute_output, end="")
        if not deploy_result.success:
            _emit_failure_hints(deploy_result)
            return 1
        tail_seconds = (
            args.tail if args.tail is not None else _DEFAULT_REPL_TAIL_SECONDS
        )
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            tail_seconds,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

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
    """``repl`` — interactive REPL, tail mode, or deploy-then-tail."""
    repl_parser = subparsers.add_parser(
        "repl",
        help=(
            "Interactive REPL on the selected board, or deploy a project "
            "and tail its output in one command."
        ),
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help=(
            "Optional project name (bare / slash / dotted).  When given, "
            "deploys the project first then enters tail mode for "
            "--tail SECONDS (default 30)."
        ),
    )
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode for SECONDS instead of the interactive "
            "TUI.  When a positional project is given, defaults to 30s."
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
            "keystrokes byte-by-byte (mpremote-style — needed for "
            "raw REPL framing or paste mode).  `auto` (default) "
            "picks `line` when stdin is a TTY and `passthrough` "
            "otherwise.  No effect with `--tail` or with a "
            "positional project (those flows always use the tail "
            "follower)."
        ),
    )
    repl_parser.set_defaults(func=_cmd_repl)
