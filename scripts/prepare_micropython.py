"""MicroPython unix-port preparation.

Clones the pinned MicroPython source tree (version from
``target-runtimes.toml``) into ``.tools/`` and compiles the unix-port
binary used for cross-runtime unit tests.

Prerequisites: ``git``, ``make``, and a C compiler (``cc``) on PATH.

Usage (via task runner)::

    python scripts/run.py prepare-micropython

The compiled binary path is written to ``.tools/micropython.path`` so
that ``resolve_micropython_binary()`` can find it without recompiling.
"""

from __future__ import annotations

import subprocess
import sys

from discovery import TOOLS
from prepare import (
    build_env,
    build_jobs,
    ensure_tool,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)

_RELEASE = runtime_versions()["micropython"]["version"]
_REPO_URL = "https://github.com/micropython/micropython.git"
_SOURCE_DIR = TOOLS / f"micropython-{_RELEASE}"
_BINARY_FILE = _SOURCE_DIR / "ports" / "unix" / "build-standard" / "micropython"


def _ensure_source_tree() -> None:
    """Clone the pinned MicroPython source tree if it is not already present.

    Always runs ``git submodule update`` even when the clone already
    exists because submodules may have been left uninitialized by a
    shallow clone or a previous interrupted run.
    """
    _SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _SOURCE_DIR.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", _RELEASE, _REPO_URL, str(_SOURCE_DIR),
        ])
    run_build_command(
        ["git", "submodule", "update", "--init", "--recursive"], cwd=_SOURCE_DIR
    )


def prepare_micropython() -> int:
    """Prepare the pinned MicroPython unix-port runtime inside the workspace."""
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-micropython` and unix-port validation."
        )
        return 2

    try:
        for tool_name in ("git", "make", "cc"):
            ensure_tool(tool_name)

        _ensure_source_tree()

        jobs = f"-j{build_jobs()}"
        # macOS Clang treats gnu-folding-constant as an error by default,
        # which breaks the MicroPython build.  Not needed on Linux/GCC.
        macos_flags = ["-Wno-error=gnu-folding-constant"] if sys.platform == "darwin" else []
        env = build_env(*macos_flags)
        # Build steps must run in order:
        #   1. mpy-cross — the bytecode compiler, required before the port.
        #   2. ports/unix — the actual unix-port interpreter binary.
        run_build_command(["make", "-C", str(_SOURCE_DIR / "mpy-cross"), jobs], env=env)
        run_build_command(["make", "-C", str(_SOURCE_DIR / "ports/unix"), jobs], env=env)
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _BINARY_FILE.exists():
        print(f"Prepared source tree does not contain the expected binary: {_BINARY_FILE}")
        return 1

    print(f"Prepared MicroPython binary: {_BINARY_FILE}")
    (TOOLS / "micropython.path").write_text(str(_BINARY_FILE))
    return 0
