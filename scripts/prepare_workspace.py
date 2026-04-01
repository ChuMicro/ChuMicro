#!/usr/bin/env python3
"""Prepare the Chumicro workspace for development and testing.

Uses whatever Python interpreter runs it.  Works with an IDE-managed
virtual environment, uv, conda, or system Python.

Usage::

    python scripts/prepare_workspace.py              # install deps + verify
    python scripts/prepare_workspace.py --create-venv  # create .venv first

The script uses only the standard library so it can run on a fresh
clone before any packages are installed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
MIN_PYTHON = (3, 11)
DEV_PACKAGES = ["pip", "pytest", "pytest-cov", "ruff", "build"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _venv_python() -> Path:
    """Return the path to the Python interpreter inside .venv."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _banner(text: str) -> None:
    """Print a visible section banner."""
    ruler = "=" * 60
    print(f"\n{ruler}\n  {text}\n{ruler}")


def _run(command: list[str | Path], label: str) -> None:
    """Run a command from the repo root and abort on failure."""
    _banner(label)
    printable = " ".join(str(c) for c in command)
    print(f"+ {printable}\n")
    result = subprocess.run([str(c) for c in command], cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFailed: {label}")
        raise SystemExit(result.returncode)


def _is_native_windows() -> bool:
    """Return whether this is native Windows (not WSL)."""
    return os.name == "nt"


def _in_virtual_env() -> bool:
    """Return whether the interpreter is running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def _describe_environment() -> str:
    """Return a short human-readable description of the active Python environment."""
    if _in_virtual_env():
        return f"virtual environment at {sys.prefix}"

    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        return f"conda environment at {conda}"

    return f"system Python at {sys.executable}"


def _missing_unix_port_tools() -> list[str]:
    """Return names of tools needed for unix-port builds that are not on PATH."""
    return [t for t in ("git", "make", "cc") if shutil.which(t) is None]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def check_python_version() -> None:
    """Fail fast if the interpreter is too old."""
    version = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info >= MIN_PYTHON:
        print(f"Python {version} — OK")
        return

    required = ".".join(str(v) for v in MIN_PYTHON)
    print(f"Python {required}+ is required. Found {version}.")
    raise SystemExit(1)


def resolve_python(create_venv: bool) -> Path:
    """Decide which Python interpreter to use for the remaining steps.

    If *create_venv* is True, create ``.venv`` (or reuse it) and return
    its interpreter.  Otherwise return the interpreter that is running
    this script.
    """
    if create_venv:
        if _venv_python().exists():
            print(f"Virtual environment exists: {VENV_DIR}")
        else:
            _banner("Creating virtual environment")
            print(f"  {VENV_DIR}\n")
            venv.create(str(VENV_DIR), with_pip=True)
        return _venv_python()

    print(f"Using {_describe_environment()}")
    if not _in_virtual_env() and not os.environ.get("CONDA_PREFIX"):
        print(
            "  Tip: pass --create-venv to create a .venv, "
            "or activate your own environment first."
        )
    return Path(sys.executable)


def install_dependencies(python: Path) -> None:
    """Install development dependencies using the chosen interpreter."""
    _run(
        [python, "-m", "pip", "install", "-U", *DEV_PACKAGES],
        "Installing development dependencies",
    )


def verify_workspace(python: Path) -> None:
    """Run lint and host tests to confirm the workspace is functional."""
    _run([python, "scripts/run.py", "lint"], "Lint")
    _run([python, "scripts/run.py", "test-host"], "Host tests")


def print_summary(python: Path) -> None:
    """Print next steps after workspace preparation."""
    _banner("Workspace is ready")
    print()

    # Activation hint only if we created .venv and it is not the running interpreter.
    if python == _venv_python() and not _in_virtual_env():
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
    print("  python scripts/run.py test-host           # CPython tests only")

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
    parser = argparse.ArgumentParser(description="Prepare the Chumicro workspace.")
    parser.add_argument(
        "--create-venv",
        action="store_true",
        help="Create a .venv virtual environment (otherwise uses the active interpreter).",
    )
    args = parser.parse_args()

    _banner("Preparing Chumicro workspace")
    print()

    check_python_version()
    python = resolve_python(args.create_venv)
    install_dependencies(python)
    verify_workspace(python)
    print_summary(python)


if __name__ == "__main__":
    main()
