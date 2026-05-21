#!/usr/bin/env python3
"""Prepare the ChuMicro workspace for development and testing.

This is the first-clone bootstrap script.  It auto-detects the Python
environment and always verifies the install before reporting success:

1. Reuse the current interpreter if it is an active venv or conda env.
2. Otherwise reuse an existing ``.venv`` at the repository root.
3. Otherwise create ``.venv`` (via ``uv`` if available, else stdlib
   ``venv``).

If the resolved interpreter is a ``.venv`` the script is *not*
currently running inside, the script re-execs itself inside that
interpreter before installing.  This lets a fresh clone bootstrap
correctly from a system Python that lacks ``tomllib`` (3.9 / 3.10) or
from any host that does not yet have ``chumicro_workspace`` on its
import path.  Both are required by the install-workspace step.

After installing dependencies and editable libraries it runs lint and
host tests to confirm the workspace is functional; use
``python scripts/run.py preflight`` for the full CI mirror.

If you already have a ready-to-use workspace (venv active, deps
installed), ``python scripts/run.py setup`` is the everyday refresh
entry point.  ``prepare_workspace.py`` is the bootstrap that runs
before any third-party packages exist.

Usage::

    python scripts/prepare_workspace.py    # auto-detect or create .venv, then verify

This script imports ``workspace`` and ``shared`` for shared helpers
(ROOT, editable-install logic).  Both modules are safe to import on a
fresh clone: ``workspace`` lazy-loads ``tomllib`` so no third-party
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

from repo_layout import ROOT
from shared import install_workspace, running_on_native_windows

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


def resolve_python() -> Path:
    """Decide which Python interpreter to use for the remaining steps.

    Looks for an active virtual environment or conda environment first,
    then an existing ``.venv`` directory, and finally creates ``.venv``
    at the repository root when nothing else is available.  This makes
    the script safe to run on a completely fresh clone without any
    flags.
    """
    # Already inside a virtual environment or conda, so use it.
    if _in_virtual_environment() or os.environ.get("CONDA_PREFIX"):
        print(f"Using {_describe_environment()}")
        return Path(sys.executable)

    # Not activated, but .venv exists at the repository root, so use it.
    if _venv_python().exists():
        print(f"Found existing virtual environment: {VENV_DIR}")
        return _venv_python()

    # No environment anywhere, so create one automatically.
    if _has_uv():
        minimum_version = ".".join(str(part) for part in MIN_PYTHON)
        _banner("Creating virtual environment (uv)")
        print(f"  {VENV_DIR}\n")
        subprocess.run(
            ["uv", "venv", "--python", f">={minimum_version}",
             str(VENV_DIR)],
            cwd=ROOT, check=True,
        )
    else:
        # stdlib venv inherits the running interpreter's version.
        # Check it first to avoid creating a useless venv.
        _check_python_version()
        _banner("Creating virtual environment")
        print(f"  {VENV_DIR}\n")
        venv.create(str(VENV_DIR), with_pip=True)
    return _venv_python()


def _reexec_into_venv_if_needed(python: Path) -> None:
    """Re-exec the script inside *python* when the host is not a venv.

    ``install_workspace()`` imports ``tomllib`` (via ``runtime_versions``)
    and ``chumicro_workspace`` (via ``generate_config_files`` / IDE-sync)
    *in the current process*.  When the host is a system Python 3.9 / 3.10
    or any interpreter without ``chumicro_workspace`` on its path, those
    imports fail.  The venv we just created has everything needed, but
    the running process cannot see it.

    Re-execing inside the venv interpreter resolves both problems: the
    new process re-enters :func:`main`, ``resolve_python`` short-circuits
    on ``_in_virtual_environment``, and ``install_workspace`` runs with
    every import available.  Returns without re-execing when we're
    already inside a venv or conda environment.

    Args:
        python: Interpreter resolved by :func:`resolve_python`.
    """
    if _in_virtual_environment() or os.environ.get("CONDA_PREFIX"):
        return

    print(f"\nRe-executing inside {python} ...\n", flush=True)
    result = subprocess.run(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=ROOT,
    )
    raise SystemExit(result.returncode)


def install_dependencies(python: Path) -> None:
    """Install the full workspace into *python*.

    Delegates to :func:`shared.install_workspace`, which is also what
    ``run.py setup`` runs.  Installs ``requirements-dev.txt`` +
    runtime-pinned type stubs + editable libraries and support
    packages, then materializes ``devices.yml`` / ``workspace.yml`` /
    ``secrets.toml`` from template files and refreshes IDE configs.

    Args:
        python: Path to the Python interpreter to install into.
    """
    _banner("Installing workspace")
    print(f"+ Target interpreter: {python}\n")
    result = install_workspace(python=python)
    if result != 0:
        print("\nFailed: Installing workspace")
        raise SystemExit(result)


def verify_workspace(python: Path) -> None:
    """Run lint and host tests to confirm the workspace is functional.

    Runs unconditionally at the end of :func:`main`.  Bootstrap only
    earns the "ready" banner once lint and host tests have actually
    passed.  Otherwise a fresh clone could report success while the
    interpreter cannot import the libraries.  Use
    ``python scripts/run.py preflight`` for the full CI mirror when
    preparing a PR.

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
        if running_on_native_windows():
            print("  .venv\\Scripts\\activate")
        else:
            print("  source .venv/bin/activate")
        print()

    print("Common tasks:")
    print("  python scripts/run.py preflight          # verify before pushing")
    if not running_on_native_windows():
        print("  python scripts/run.py test-all-runtimes # full cross-runtime tests")
    print("  python scripts/run.py test                # CPython tests only")

    if running_on_native_windows():
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
    argparse.ArgumentParser(
        description="Prepare the ChuMicro workspace. Auto-creates .venv when "
        "no environment is active or present at the repository root, installs "
        "dependencies, then runs lint + host tests to confirm the install.",
    ).parse_args()

    _banner("Preparing ChuMicro workspace")
    print()

    python = resolve_python()
    _check_python_version(python)
    _reexec_into_venv_if_needed(python)
    install_dependencies(python)
    verify_workspace(python)
    print_summary(python)


if __name__ == "__main__":
    main()
