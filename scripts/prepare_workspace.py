#!/usr/bin/env python3
"""Prepare the Chumicro workspace for development and testing.

Run once after cloning the repository::

    python scripts/prepare_workspace.py

The script creates a virtual environment, installs development
dependencies, and verifies the workspace is ready for iteration.

It uses only the Python standard library so it can bootstrap a
fresh clone without any prior ``pip install``.
"""

from __future__ import annotations

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
    """Return the path to the Python interpreter inside the virtual environment."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _banner(text: str) -> None:
    """Print a visible section banner."""
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


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


def _missing_unix_port_tools() -> list[str]:
    """Return names of tools required for unix-port builds that are not on PATH."""
    return [t for t in ("git", "make", "cc") if shutil.which(t) is None]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def check_python_version() -> None:
    """Fail fast if the interpreter is too old."""
    if sys.version_info >= MIN_PYTHON:
        version = ".".join(str(v) for v in sys.version_info[:3])
        print(f"Python {version} — OK")
        return

    version = ".".join(str(v) for v in sys.version_info[:3])
    required = ".".join(str(v) for v in MIN_PYTHON)
    print(f"Python {required}+ is required. Found {version}.")
    raise SystemExit(1)


def create_venv() -> None:
    """Create the virtual environment if it does not exist yet."""
    if _venv_python().exists():
        print(f"Virtual environment exists: {VENV_DIR}")
        return

    _banner("Creating virtual environment")
    print(f"  {VENV_DIR}\n")
    venv.create(str(VENV_DIR), with_pip=True)


def install_dependencies() -> None:
    """Install development dependencies into the virtual environment."""
    _run(
        [_venv_python(), "-m", "pip", "install", "-U", *DEV_PACKAGES],
        "Installing development dependencies",
    )


def verify_workspace() -> None:
    """Run lint and host tests to confirm the workspace is functional."""
    python = _venv_python()
    _run([python, "ci/tasks.py", "lint"], "Lint")
    _run([python, "ci/tasks.py", "test-host"], "Host tests")


def print_summary() -> None:
    """Print activation instructions and next steps."""
    _banner("Workspace is ready")
    print()

    if _is_native_windows():
        print("Activate the virtual environment:")
        print("  .venv\\Scripts\\activate")
        print()
        print("Common tasks:")
        print("  python ci/tasks.py preflight          # verify before pushing")
        print("  python ci/tasks.py test-host           # CPython tests only")
        print()
        print("Windows note:")
        print("  Unix-port runtime checks (MicroPython, CircuitPython) require WSL2.")
        print("  Native Windows supports lint, host tests, and package builds.")
    else:
        print("Activate the virtual environment:")
        print("  source .venv/bin/activate")
        print()
        print("Common tasks:")
        print("  python ci/tasks.py preflight          # verify before pushing")
        print("  python ci/tasks.py test-runtime-matrix # full cross-runtime tests")
        print("  python ci/tasks.py test-host           # CPython tests only")

        missing = _missing_unix_port_tools()
        if missing:
            print()
            print(f"Optional: install {', '.join(missing)} to enable unix-port builds.")
            print("  The runtime-matrix task will build them automatically on first run.")


def main() -> None:
    """Prepare the workspace for development and testing."""
    _banner("Preparing Chumicro workspace")
    print()

    check_python_version()
    create_venv()
    install_dependencies()
    verify_workspace()
    print_summary()


if __name__ == "__main__":
    main()
