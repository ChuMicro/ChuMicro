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
        help="Register a new board and print what to run next.  Start here.",
        description=(
            "Register the board plugged into USB.  bootstrap finds the "
            "board's serial port, works out whether it runs CircuitPython "
            "or MicroPython, and records it in devices.yml, the same "
            "steps add-device runs.  It then prints the commands that "
            "create a project, deploy it, and open the board's prompt.  "
            "--demo also sends the board a counting program, so it "
            "prints something straight away.  A board with no "
            "CircuitPython or MicroPython on it needs firmware from "
            "circuitpython.org or micropython.org first."
        ),
    )
    _add_workspace_arg(bootstrap_parser)
    bootstrap_parser.add_argument(
        "id",
        nargs="?",
        default=None,
        help=(
            "Name for the board in devices.yml, such as back-porch.  "
            "Without it, the name comes from the board's model and "
            "runtime, such as raspberry-pi-pico-w-cp."
        ),
    )
    bootstrap_parser.add_argument(
        "--address",
        default=None,
        help=(
            "Serial port the board is on, such as /dev/cu.usbmodem1101 "
            "or COM3.  Without it, bootstrap uses the only port it sees, "
            "or lists the ports and asks you to pick one.  Required "
            "with --non-interactive."
        ),
    )
    bootstrap_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Runtime the board runs.  Without it, bootstrap tries "
            "both."
        ),
    )
    bootstrap_parser.add_argument(
        "--description",
        default=None,
        help=(
            "Note stored with the entry, such as 'kitchen window "
            "sensor'.  Later commands keep it as you wrote it."
        ),
    )
    bootstrap_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Replace the entry that already has this id, after you swap "
            "in a different board under the same name."
        ),
    )
    bootstrap_parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "After registering, send the board a counting program and "
            "show its first output."
        ),
    )
    _add_non_interactive_arg(bootstrap_parser)
    bootstrap_parser.set_defaults(func=_cmd_bootstrap)
