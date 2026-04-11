#!/usr/bin/env python3
"""Prepare the ChuMicro workspace for development and testing.

Uses whatever Python interpreter runs it.  Works with an IDE-managed
virtual environment, uv, or ``--create-venv`` for a fresh start.

Usage::

    python scripts/prepare_workspace.py              # install dependencies + verify
    python scripts/prepare_workspace.py --create-venv  # create .venv first

This script imports ``workspace`` and ``shared`` for shared helpers
(ROOT, editable-install logic).  Both modules are safe to import on a
fresh clone — ``workspace`` lazy-loads ``tomllib`` so no third-party
packages are needed at import time.  The code itself is compatible with
Python 3.7+ so ``_check_python_version()`` can deliver a friendly error
on older interpreters.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from shared import install_command, install_editable
from workspace import ROOT

VENV_DIR = ROOT / ".venv"
#: Minimum Python for the workspace (pytest 8, hatchling, griffe need 3.8+;
#: 3.9 is the oldest version with broad community support).  tomllib was
#: the previous hard 3.11 floor — now covered by the tomli backport.
#: The version check runs against the *resolved* interpreter after venv
#: creation — not the system Python.  This lets uv create a suitable venv
#: even when the system default is older.  This script itself runs on
#: 3.7+ so it can deliver a friendly error on any interpreter.
MIN_PYTHON = (3, 9)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _venv_python() -> Path:
    """Return the path to the Python interpreter inside .venv."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _banner(text: str) -> None:
    """Print a visible section banner.

    Args:
        text: Banner message.
    """
    ruler = "=" * 60
    print(f"\n{ruler}\n  {text}\n{ruler}")


def _run(command: list[str | Path], label: str) -> None:
    """Run a command from the repository root and abort on failure.

    Args:
        command: Command and arguments to run.
        label: Human-readable step label for error reporting.
    """
    _banner(label)
    printable = " ".join(str(arg) for arg in command)
    print(f"+ {printable}\n")
    result = subprocess.run([str(arg) for arg in command], cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFailed: {label}")
        raise SystemExit(result.returncode)


def _is_native_windows() -> bool:
    """Return whether this is native Windows (not WSL)."""
    return os.name == "nt"


def _in_virtual_environment() -> bool:
    """Return whether the interpreter is running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def _describe_environment() -> str:
    """Return a short human-readable description of the active Python environment."""
    if _in_virtual_environment():
        return f"virtual environment at {sys.prefix}"

    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        return f"conda environment at {conda}"

    return f"system Python at {sys.executable}"


def _missing_unix_port_tools() -> list[str]:
    """Return names of tools needed for unix-port builds that are not on PATH."""
    return [tool for tool in ("git", "make", "cc") if shutil.which(tool) is None]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _check_python_version(python: Path | None = None) -> None:
    """Verify that an interpreter meets the minimum workspace version.

    When *python* is ``None``, checks the running interpreter directly
    (fast, no subprocess).  When *python* is a path, shells out to query
    the target interpreter.

    Args:
        python: Path to the interpreter to check, or ``None`` for the
            running interpreter.
    """
    if python is None:
        version = ".".join(str(part) for part in sys.version_info[:3])
        ok = sys.version_info[:2] >= MIN_PYTHON
    else:
        result = subprocess.run(
            [str(python), "-c",
             "import sys; print('.'.join(str(part) for part in sys.version_info[:3]))"],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode != 0:
            print(f"Cannot determine Python version: {python}")
            raise SystemExit(1)
        version = result.stdout.strip()
        parts = tuple(int(part) for part in version.split(".")[:2])
        ok = parts >= MIN_PYTHON

    if ok:
        print(f"Python {version} — OK")
        return

    required = ".".join(str(part) for part in MIN_PYTHON)
    print(f"Python {required}+ is required. Found {version}.")
    raise SystemExit(1)


def _has_uv() -> bool:
    """Return whether the ``uv`` package manager is available on PATH."""
    return shutil.which("uv") is not None


def resolve_python(create_venv: bool) -> Path:
    """Decide which Python interpreter to use for the remaining steps.

    If *create_venv* is True, create ``.venv`` (or reuse it) and return
    its interpreter.

    If *create_venv* is False, the script looks for an active virtual
    environment or conda environment first, then checks whether a
    ``.venv`` directory already exists.

    Args:
        create_venv: Whether to create a new virtual environment.
    """
    if create_venv:
        if _venv_python().exists():
            print(f"Virtual environment exists: {VENV_DIR}")
        elif _has_uv():
            minimum_version = ".".join(str(part) for part in MIN_PYTHON)
            _banner("Creating virtual environment (uv)")
            print(f"  {VENV_DIR}\n")
            subprocess.run(
                ["uv", "venv", "--python", f">={minimum_version}",
                 str(VENV_DIR)],
                cwd=ROOT, check=True,
            )
        else:
            # stdlib venv inherits the running interpreter's version —
            # check it first to avoid creating a useless venv.
            _check_python_version()
            _banner("Creating virtual environment")
            print(f"  {VENV_DIR}\n")
            venv.create(str(VENV_DIR), with_pip=True)
        return _venv_python()

    # Already inside a virtual environment or conda — use it.
    if _in_virtual_environment() or os.environ.get("CONDA_PREFIX"):
        print(f"Using {_describe_environment()}")
        return Path(sys.executable)

    # Not activated, but .venv exists at the repository root — use it.
    if _venv_python().exists():
        print(f"Found existing virtual environment: {VENV_DIR}")
        return _venv_python()

    # No environment available — refuse to install into system Python.
    print("No virtual environment detected.")
    print()
    print("Options:")
    print("  python scripts/prepare_workspace.py --create-venv   # create .venv")
    print("  source .venv/bin/activate                           # activate existing")
    print("  uv venv && source .venv/bin/activate                # create with uv")
    raise SystemExit(1)


def install_dependencies(python: Path) -> None:
    """Install development dependencies using the chosen interpreter.

    Args:
        python: Path to the Python interpreter.
    """
    requirements_file = str(ROOT / "requirements-dev.txt")
    _run(
        [*install_command(python), "-U", "-r", requirements_file],
        "Installing development dependencies",
    )

    # Editable-install all libraries so imports work in any tool
    # (editors, debuggers, REPLs) without manual PYTHONPATH setup.
    _banner("Installing libraries (editable)")
    result = install_editable(python=python)
    if result != 0:
        print("\nFailed: Installing libraries (editable)")
        raise SystemExit(result)


def verify_workspace(python: Path) -> None:
    """Run lint and host tests to confirm the workspace is functional.

    Args:
        python: Path to the Python interpreter.
    """
    _run([python, "scripts/run.py", "lint"], "Lint")
    _run([python, "scripts/run.py", "test"], "Host tests")


def print_summary(python: Path) -> None:
    """Print next steps after workspace preparation.

    Args:
        python: Path to the Python interpreter used for setup.
    """
    _banner("Workspace is ready")
    print()

    # Activation hint only if we created .venv and it is not the running interpreter.
    if python == _venv_python() and not _in_virtual_environment():
        print("Activate the virtual environment:")
        if _is_native_windows():
            print("  .venv\\Scripts\\activate")
        else:
            print("  source .venv/bin/activate")
        print()

    print("Common tasks:")
    print("  python scripts/run.py preflight          # verify before pushing")
    if not _is_native_windows():
        print("  python scripts/run.py test-runtime-matrix # full cross-runtime tests")
    print("  python scripts/run.py test                # CPython tests only")

    if _is_native_windows():
        print()
        print("Windows note:")
        print("  Unix-port runtime checks (MicroPython, CircuitPython) require WSL2.")
        print("  Native Windows supports lint, host tests, and package builds.")
    else:
        missing = _missing_unix_port_tools()
        if missing:
            print()
            names = ", ".join(missing)
            print(f"Optional: install {names} to enable unix-port builds.")
            print("  The runtime-matrix task will build them automatically on first run.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Prepare the workspace for development and testing."""
    parser = argparse.ArgumentParser(description="Prepare the ChuMicro workspace.")
    parser.add_argument(
        "--create-venv",
        action="store_true",
        help="Create a .venv virtual environment (otherwise uses the active interpreter).",
    )
    args = parser.parse_args()

    _banner("Preparing ChuMicro workspace")
    print()

    python = resolve_python(args.create_venv)
    _check_python_version(python)
    install_dependencies(python)
    verify_workspace(python)
    print_summary(python)


if __name__ == "__main__":
    main()
