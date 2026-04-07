#!/usr/bin/env python3
"""Prepare the Chumicro workspace for development and testing.

Uses whatever Python interpreter runs it.  Works with an IDE-managed
virtual environment, uv, or ``--create-venv`` for a fresh start.

Usage::

    python scripts/prepare_workspace.py              # install dependencies + verify
    python scripts/prepare_workspace.py --create-venv  # create .venv first

This script is deliberately standalone — it imports only the standard
library so it can run on a fresh clone before any packages are installed.
Its own code is compatible with Python 3.7+, so it can deliver a
friendly version error on older interpreters before anything breaks.
``discovery.py`` is currently stdlib-only too, but coupling this
bootstrap entry point to it would make ``check_python_version()``
fragile: any future module-level import in ``discovery.py`` that
requires 3.11+ (e.g. ``tomllib``) would replace the friendly message
with a confusing ``ModuleNotFoundError``.
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
    """Print a visible section banner."""
    ruler = "=" * 60
    print(f"\n{ruler}\n  {text}\n{ruler}")


def _run(command: list[str | Path], label: str) -> None:
    """Run a command from the repository root and abort on failure."""
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
    return [tool for tool in ("git", "make", "cc") if shutil.which(tool) is None]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _check_python_version(python: Path | None = None) -> None:
    """Verify that an interpreter meets the minimum workspace version.

    When *python* is ``None``, checks the running interpreter directly
    (fast, no subprocess).  When *python* is a path, shells out to query
    the target interpreter — needed after creating a venv whose Python
    may differ from the one running this script.
    """
    if python is None:
        version = ".".join(str(part) for part in sys.version_info[:3])
        ok = sys.version_info[:2] >= MIN_PYTHON
    else:
        result = subprocess.run(
            [str(python), "-c",
             "import sys; print('.'.join(str(v) for v in sys.version_info[:3]))"],
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
    its interpreter.  Prefers ``uv venv`` when uv is on PATH (faster,
    no pip bootstrapping needed), falling back to stdlib ``venv``.

    If *create_venv* is False, the script looks for an active virtual
    environment or conda environment first, then checks whether a
    ``.venv`` directory already exists at the repository root.  If none of
    these apply, the script refuses to continue rather than installing
    into system Python.
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
    if _in_virtual_env() or os.environ.get("CONDA_PREFIX"):
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

    Prefers ``uv pip install`` when uv is on PATH, falling back to
    ``python -m pip install``.  The ``--python`` flag tells uv which
    environment to target even if it has not been activated yet.
    """
    requirements_file = str(ROOT / "requirements-dev.txt")
    if _has_uv():
        _run(
            ["uv", "pip", "install", "--python", str(python), "-U",
             "-r", requirements_file],
            "Installing development dependencies (uv)",
        )
    else:
        _run(
            [python, "-m", "pip", "install", "-U", "-r", requirements_file],
            "Installing development dependencies",
        )


def verify_workspace(python: Path) -> None:
    """Run lint and host tests to confirm the workspace is functional."""
    _run([python, "scripts/run.py", "lint"], "Lint")
    _run([python, "scripts/run.py", "test"], "Host tests")


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
    parser = argparse.ArgumentParser(description="Prepare the Chumicro workspace.")
    parser.add_argument(
        "--create-venv",
        action="store_true",
        help="Create a .venv virtual environment (otherwise uses the active interpreter).",
    )
    args = parser.parse_args()

    _banner("Preparing Chumicro workspace")
    print()

    python = resolve_python(args.create_venv)
    _check_python_version(python)
    install_dependencies(python)
    verify_workspace(python)
    print_summary(python)


if __name__ == "__main__":
    main()
