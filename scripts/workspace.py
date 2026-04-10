"""Workspace operations — subprocess helpers and package installation.

Provides shared utilities that scripts use to run commands from the
repository root and manage installed packages.  Builds on
:mod:`discovery` for package enumeration.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from discovery import ROOT, find_publishable_packages


def run_command(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a command from the repository root and return its exit code.

    Args:
        command: Command and arguments to run.
        env: Optional environment variables to pass to the subprocess.

    Returns:
        Process exit code.
    """
    printable = " ".join(command)
    print(f"+ {printable}")
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def install_command(python: str | Path | None = None) -> list[str]:
    """Return the pip-install command prefix, preferring uv when available.

    Args:
        python: Interpreter to target.  When *None*, targets the running
            interpreter.  With ``uv`` this becomes ``--python <path>``;
            without ``uv`` it replaces ``sys.executable``.
    """
    if shutil.which("uv"):
        command = ["uv", "pip", "install"]
        if python is not None:
            command.extend(["--python", str(python)])
        return command
    interpreter = str(python) if python is not None else sys.executable
    return [interpreter, "-m", "pip", "install"]


def install_editable(python: str | Path | None = None) -> int:
    """Install all publishable libraries as editable packages.

    This registers each library with Python's import system so that
    imports work in any tool (editors, debuggers, REPLs, scripts)
    without manual PYTHONPATH setup.  Changes to source files are
    reflected immediately — no reinstall needed.

    Args:
        python: Interpreter to install into.  Defaults to the running
            interpreter when *None*.

    Returns:
        Process exit code (0 on success).
    """
    packages = find_publishable_packages()
    if not packages:
        return 0

    editable_args: list[str] = []
    for package in packages:
        editable_args.extend(["-e", package])

    return run_command([*install_command(python), *editable_args])

