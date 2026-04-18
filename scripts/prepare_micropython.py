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

from shared import (
    build_jobs,
    ensure_build_tools,
    ensure_source_tree,
    macos_build_environment,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)
from workspace import TOOLS

_REPO_URL = "https://github.com/micropython/micropython.git"

# Only these submodules are required for the unix-port build.
# The full recursive init pulls ~1.4GB of board-specific libraries
# (stm32lib, pico-sdk, nxp_driver, etc.) that are never used.
_UNIX_PORT_SUBMODULES = [
    "lib/berkeley-db-1.xx",
    "lib/libffi",
    "lib/mbedtls",  # SSL/TLS and crypto
    "lib/micropython-lib",  # Frozen stdlib modules
]


def _source_dir():
    """Return the MicroPython source directory (computed lazily)."""
    release = runtime_versions()["micropython"]["version"]
    return TOOLS / f"micropython-{release}"


def _binary_file():
    """Return the expected binary path (computed lazily)."""
    return _source_dir() / "ports" / "unix" / "build-standard" / "micropython"


def prepare_micropython() -> int:
    """Prepare the pinned MicroPython unix-port runtime inside the workspace."""
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-micropython` and unix-port validation."
        )
        return 2

    try:
        ensure_build_tools()

        source_dir = _source_dir()
        release = runtime_versions()["micropython"]["version"]
        ensure_source_tree(source_dir, _REPO_URL, release)

        # Init only the submodules needed for unix-port (not recursive).
        for submodule in _UNIX_PORT_SUBMODULES:
            run_build_command(
                ["git", "submodule", "update", "--init", submodule],
                cwd=source_dir,
            )

        jobs = f"-j{build_jobs()}"
        environment = macos_build_environment()
        # Build steps must run in order:
        #   1. mpy-cross — the bytecode compiler, required before the port.
        #   2. ports/unix — the actual unix-port interpreter binary.
        run_build_command(
            ["make", "-C", str(source_dir / "mpy-cross"), jobs],
            environment=environment,
        )
        run_build_command(
            ["make", "-C", str(source_dir / "ports/unix"), jobs],
            environment=environment,
        )
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    binary_file = _binary_file()
    if not binary_file.exists():
        print(f"Prepared source tree does not contain the expected binary: {binary_file}")
        return 1

    print(f"Prepared MicroPython binary: {binary_file}")
    (TOOLS / "micropython.path").write_text(str(binary_file))
    return 0
