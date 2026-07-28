"""``bootstrap`` subcommand: onboarding entry point.

Thin wrapper over ``add-device``: same probe + register flow, plus a
"next steps" footer aimed at first-time users.  ``--demo`` is the
opt-in flag for chaining into the built-in demo after register.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from chumicro_workspace.cli._common import (
    _add_non_interactive_arg,
    _add_workspace_arg,
    _stdin_prompt,
)
from chumicro_workspace.cli.devices import _cmd_add_device


def _print_bootstrap_next_steps() -> None:
    """Print the new / deploy / repl pointer block."""
    print()
    print("bootstrap: ready.  Next steps:")
    print(
        "  python3 run.py new <project-name>      "
        "# create a new project under projects/",
    )
    print(
        "  python3 run.py deploy                "
        "# deploy your only project (no name needed)",
    )
    print(
        "  python3 run.py repl                  "
        "# open the REPL on your board",
    )


def _cmd_bootstrap(
    args: argparse.Namespace,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> int:
    """Onboard a board: delegate to ``add-device`` then print next steps.

    The remaining unique behavior beyond ``add-device`` is the
    "next steps" footer pointing at ``new`` / ``deploy`` / ``repl``,
    aimed at first-time users.  Every other concern (port-pick,
    runtime auto-detection, register, optional demo chain) lives in
    ``add-device`` and is shared.
    """
    exit_code = _cmd_add_device(args, prompt_func=prompt_func)
    if exit_code == 0:
        _print_bootstrap_next_steps()
    return exit_code


def _add_bootstrap_parser(subparsers: argparse._SubParsersAction) -> None:
    """``bootstrap``: onboarding entry-point alias of ``add-device`` + footer."""
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help=(
            "Onboarding entry point: same as `add-device` plus a "
            "next-steps footer pointing at `new` / `deploy` / `repl`.  "
            "Pass --demo to chain into the built-in demo deploy after "
            "register."
        ),
    )
    _add_workspace_arg(bootstrap_parser)
    bootstrap_parser.add_argument(
        "id",
        nargs="?",
        default=None,
        help=(
            "User-friendly device id (e.g. 'back-porch-mp').  Optional: "
            "when omitted, a default is derived from the probe's "
            "machine string + runtime suffix."
        ),
    )
    bootstrap_parser.add_argument(
        "--address",
        default=None,
        help=(
            "Serial port path of the connected board.  Optional: when "
            "omitted in interactive mode, the wizard auto-picks the "
            "only detected port or prompts with a numbered list when "
            "multiple are present."
        ),
    )
    bootstrap_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help="Runtime to probe.  Optional: auto-detected when omitted.",
    )
    bootstrap_parser.add_argument(
        "--description",
        default=None,
        help="Free-form note recorded under 'description:'.",
    )
    bootstrap_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing entry with this id.",
    )
    bootstrap_parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "After registering, chain into the built-in demo deploy "
            "so a freshly registered board ships *something* in one "
            "command."
        ),
    )
    _add_non_interactive_arg(bootstrap_parser)
    bootstrap_parser.set_defaults(func=_cmd_bootstrap)
