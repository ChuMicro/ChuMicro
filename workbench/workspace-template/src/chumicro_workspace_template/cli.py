"""``chumicro-workspace-template`` command dispatcher.

Two commands:

* ``init <target> [--from <source>] [--force]`` — scaffold a fresh
  workspace at *target* from *source* (defaults to built-in
  template).
* ``update [<target>] [--from <source>]`` — refresh the tool-owned
  slice of an existing workspace.  *target* defaults to ``cwd``.

Returns exit code 0 on success, 1 when a target directory contains
existing files that ``init`` refuses to overwrite (caller should
re-run with ``--force`` if intentional), 2 on argparse errors or
missing source / target, 3 on unexpected I/O failure.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chumicro_workspace_template.apply import (
    ApplyAction,
    ApplyReport,
    init,
    update,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace-template",
        description=(
            "Scaffold + update ChuMicro project workspaces.  Lays down "
            "a starter tree on `init` and re-applies tool-owned files "
            "on `update` without clobbering user code."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Lay down a fresh workspace at <target>.",
    )
    init_parser.add_argument(
        "target",
        type=Path,
        help="Workspace directory to create / populate.",
    )
    init_parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help=(
            "Custom template source (local path).  Defaults to the "
            "built-in template shipped with this package."
        ),
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite files at <target> that already exist.  Without "
            "this, `init` skips conflicts and reports them so re-running "
            "is idempotent."
        ),
    )
    init_parser.set_defaults(func=_cmd_init)

    update_parser = subparsers.add_parser(
        "update",
        help=(
            "Refresh tool-owned files in an existing workspace.  Never "
            "touches user-owned files (things/, secrets.yml, etc.)."
        ),
    )
    update_parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=None,
        help="Workspace directory.  Defaults to the current directory.",
    )
    update_parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="Custom template source.  Defaults to the built-in template.",
    )
    update_parser.set_defaults(func=_cmd_update)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* and dispatch.  Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except NotADirectoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _cmd_init(args: argparse.Namespace) -> int:
    report = init(args.target, source=args.source, force=args.force)
    _print_report(report)
    if report.count(ApplyAction.SKIPPED) > 0 and not args.force:
        # Inform the user that some files were preserved; re-run with
        # --force if they wanted the template to win.
        return 1
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    target = args.target if args.target is not None else Path.cwd()
    report = update(target, source=args.source)
    _print_report(report)
    return 0


def _print_report(report: ApplyReport) -> None:
    """Summarize *report*'s actions on stdout."""
    written = report.count(ApplyAction.WRITTEN)
    refreshed = report.count(ApplyAction.REFRESHED)
    unchanged = report.count(ApplyAction.UNCHANGED)
    skipped = report.count(ApplyAction.SKIPPED)
    print(
        f"summary: written={written} refreshed={refreshed} "
        f"unchanged={unchanged} skipped={skipped}",
    )
    for path, action in report:
        print(f"  {action:>10}  {path}")
