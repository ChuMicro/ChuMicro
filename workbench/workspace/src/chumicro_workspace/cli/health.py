"""``status`` / ``doctor`` subcommands and the macOS FSKit recovery wrapper.

Both commands collect findings via :mod:`chumicro_workspace.health` and
render them through the same one-line-per-check formatter.  ``doctor``
adds the strict Python-version + per-project AST checks.  The
``--fix-fskit-wedge`` mode on ``doctor`` dispatches to the macOS sudo
recovery wrapper instead of the static checks.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

from chumicro_deploy.macos_fskit import (
    MACOS_FSKIT_RECOVERY_COMMAND,
    detect_fskit_wedge,
)

from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _resolve_workspace,
)
from chumicro_workspace.health import (
    HealthFinding,
    HealthLevel,
    collect_doctor_findings,
    collect_health_findings,
)
from chumicro_workspace.workspace import WorkspaceLayout

#: Glyphs for ``status`` line prefixes.  Plain Unicode dingbats so
#: every reasonable terminal renders them; downstream consumers
#: that want strict ASCII can pipe through ``sed`` to remap.
_HEALTH_LEVEL_PREFIX: dict[HealthLevel, str] = {
    HealthLevel.OK: "✓",
    HealthLevel.WARN: "⚠",
    HealthLevel.ERROR: "✗",
}

def _format_health_finding(finding: HealthFinding, label_width: int) -> str:
    """Return the one-line representation of *finding* for ``status``."""
    prefix = _HEALTH_LEVEL_PREFIX[finding.level]
    label = finding.label.ljust(label_width)
    return f"{label}{prefix} {finding.message}"


def _print_health_findings(
    workspace: WorkspaceLayout,
    findings: list[HealthFinding],
) -> int:
    """Print *findings* with the status/doctor renderer; return exit code.

    Header line carries the workspace root.  Each finding renders as
    ``LABEL <glyph> message``.  Warning / error findings carry an
    optional hint indented under the label column.  Exit code flips
    to 1 only on at least one ERROR.  Warnings stay at 0 so the
    output composes cleanly with shell-pipe checks.
    """
    # Label column sized from the longest label actually printed plus
    # a 2-space gutter: status and doctor carry different label sets,
    # and a fixed width drifts out of alignment the first time a new
    # check ships a longer label.
    label_width = 2 + max(
        [len("WORKSPACE"), *(len(finding.label) for finding in findings)],
    )
    print(f"{'WORKSPACE'.ljust(label_width)}{workspace.root}")
    has_error = False
    for finding in findings:
        print(_format_health_finding(finding, label_width))
        if finding.hint and finding.level is not HealthLevel.OK:
            print(f"{' ' * label_width}  hint: {finding.hint}")
        if finding.level is HealthLevel.ERROR:
            has_error = True
    return 1 if has_error else 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Print a one-line-per-check workspace health snapshot.

    Runs the three fast static checks (workspace.yml validity,
    devices.yml count, projects tree summary).  See :func:`_cmd_doctor`
    for the stricter variant.
    """
    workspace = _resolve_workspace(args)
    return _print_health_findings(workspace, collect_health_findings(workspace))


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Strict sibling of ``status``: also checks the host Python
    version and AST-walks each project's ``app.py`` for a top-level
    ``run()``.  Same renderer and exit codes as ``status`` (errors
    → 1, warnings → 0).

    ``--fix-fskit-wedge`` short-circuits to the macOS FSKit recovery
    wrapper before any workspace is resolved.
    """
    if getattr(args, "fix_fskit_wedge", False):
        return _fix_fskit_wedge(args._env.subprocess_runner)
    workspace = _resolve_workspace(args)
    return _print_health_findings(workspace, collect_doctor_findings(workspace))


#: Distinct exit codes for the ``--fix-fskit-wedge`` path so scripted
#: callers can tell *why* the wrapper refused to run.  ``0`` is wedge
#: cleared; ``1`` (default) is reserved for genuine command-failure
#: paths the runner picks up.
_FSKIT_FIX_EXIT_NOT_DARWIN = 2
_FSKIT_FIX_EXIT_NOT_WEDGED = 3
_FSKIT_FIX_EXIT_NO_TTY = 4
_FSKIT_FIX_EXIT_NO_SUDO = 5
_FSKIT_FIX_EXIT_PERSISTS = 6


def _fix_fskit_wedge(
    subprocess_runner: Callable[..., subprocess.CompletedProcess],
) -> int:
    """Opt-in sudo wrapper around :data:`MACOS_FSKIT_RECOVERY_COMMAND`.

    Refuses on non-macOS, when no wedge is detected (running the
    killall on a healthy system damages mounted volumes), when
    stdin/stderr are not a TTY (sudo can't prompt for a password),
    or when ``sudo`` is not on PATH.  When all checks pass, runs the
    killall, settles 2 s, re-runs detection, and reports.  Distinct
    exit codes per refusal class so scripted callers can branch.
    """
    if sys.platform != "darwin":
        print(
            "[chumicro-workspace] FSKit wedge recovery is macOS-only.",
            file=sys.stderr,
        )
        return _FSKIT_FIX_EXIT_NOT_DARWIN

    if not detect_fskit_wedge():
        print(
            "[chumicro-workspace] No FSKit wedge detected; refusing "
            "to run the recovery command.\n"
            "Running it on a healthy system kills daemons mid-"
            "operation on mounted volumes and leaves them in an "
            "I/O-error state that needs physical replug to recover.",
            file=sys.stderr,
        )
        return _FSKIT_FIX_EXIT_NOT_WEDGED

    # sudo prompts for the password on stderr by default.  If either
    # stdin (where it reads the password) or stderr (where it writes
    # the prompt) is not a TTY, the prompt either silently hangs or
    # the user can't see it.  Refuse and surface the paste fallback.
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print(
            "[chumicro-workspace] Cannot prompt for sudo on a non-"
            "interactive shell.  Paste this into a Terminal tab "
            f"manually:\n    {MACOS_FSKIT_RECOVERY_COMMAND}",
            file=sys.stderr,
        )
        return _FSKIT_FIX_EXIT_NO_TTY

    if shutil.which("sudo") is None:
        print(
            "[chumicro-workspace] `sudo` is not on PATH.  Paste this "
            f"manually:\n    {MACOS_FSKIT_RECOVERY_COMMAND}",
            file=sys.stderr,
        )
        return _FSKIT_FIX_EXIT_NO_SUDO

    print(
        "[chumicro-workspace] FSKit wedge detected.  Running recovery "
        "(sudo will prompt for your password).",
    )
    # MACOS_FSKIT_RECOVERY_COMMAND is the literal "sudo killall -9
    # <daemon> <daemon> ..." line.  Whitespace-split is safe because
    # the constant has no quoting / shell metacharacters.
    completed = subprocess_runner(  # noqa: S603 - argv from a vetted constant
        MACOS_FSKIT_RECOVERY_COMMAND.split(),
        check=False,
    )
    if completed.returncode != 0:
        print(
            "[chumicro-workspace] Recovery command failed (exit "
            f"{completed.returncode}).  Reboot is the always-safe "
            "alternative.",
            file=sys.stderr,
        )
        return completed.returncode

    # Daemons respawn under launchd; give them a beat before
    # re-checking so the detector doesn't catch the gap between the
    # killall returning and the new ``diskarbitrationd`` registering
    # its process state.
    time.sleep(2.0)
    if detect_fskit_wedge():
        print(
            "[chumicro-workspace] Wedge persists after killall.  "
            "Reboot is the always-safe alternative.",
            file=sys.stderr,
        )
        return _FSKIT_FIX_EXIT_PERSISTS

    print("[chumicro-workspace] FSKit wedge cleared.")
    return 0


def _add_health_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``status`` / ``doctor`` subparsers."""
    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Print a one-line-per-check workspace health snapshot "
            "(workspace.yml validity, devices.yml count, "
            "projects tree summary)."
        ),
    )
    _add_workspace_arg(status_parser)
    status_parser.set_defaults(func=_cmd_status)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help=(
            "Strict sibling of `status`: adds Python version check "
            "and a per-project AST scan for `run()`."
        ),
    )
    _add_workspace_arg(doctor_parser)
    doctor_parser.add_argument(
        "--fix-fskit-wedge",
        action="store_true",
        dest="fix_fskit_wedge",
        help=(
            "macOS only.  Detect the FSKit wedge and, if present, "
            "run the sudo killall recovery command for you (sudo "
            "prompts for your password inline).  Refuses to run "
            "when no wedge is detected, because running the recovery on a "
            "healthy system damages mounted volumes."
        ),
    )
    doctor_parser.set_defaults(func=_cmd_doctor)
