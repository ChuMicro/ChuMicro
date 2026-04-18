"""CircuitPython unix-port preparation.

Clones the pinned CircuitPython source tree (version from
``target-runtimes.toml``) into ``.tools/`` and compiles the unix-port
binary used for cross-runtime unit tests.

Prerequisites: ``git``, ``make``, and a C compiler (``cc``) on PATH.

Usage (via task runner)::

    python scripts/run.py prepare-circuitpython

The compiled binary path is written to ``.tools/circuitpython.path`` so
that ``resolve_circuitpython_binary()`` can find it without recompiling.

Note: CircuitPython is an Adafruit fork of MicroPython.  The unix-port
binary is named ``micropython`` (inherited from the upstream project),
which is expected — see ``_BINARY_FILE`` below.
"""

from __future__ import annotations

import subprocess
import sys

from shared import (
    build_environment,
    build_jobs,
    ensure_build_tools,
    ensure_source_tree,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)
from workspace import TOOLS

_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_UNIX_VARIANT = "standard"


def _source_dir():
    """Return the CircuitPython source directory (computed lazily)."""
    release = runtime_versions()["circuitpython"]["version"]
    return TOOLS / f"circuitpython-{release}"


def _binary_file():
    """Return the expected binary path (computed lazily).

    The CircuitPython unix-port binary is named "micropython" — inherited
    from the MicroPython fork.  This is expected, not a misconfiguration.
    """
    return _source_dir() / "ports" / "unix" / f"build-{_UNIX_VARIANT}" / "micropython"


def prepare_circuitpython() -> int:
    """Prepare the pinned CircuitPython unix-port runtime inside the workspace."""
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-circuitpython` and unix-port validation."
        )
        return 2

    try:
        ensure_build_tools()

        source_dir = _source_dir()
        release = runtime_versions()["circuitpython"]["version"]
        ensure_source_tree(source_dir, _REPO_URL, release)

        jobs = f"-j{build_jobs()}"
        # Build steps must run in this exact order:
        #   1. ci_fetch_deps.py — fetches git submodules and vendored dependencies
        #      that mpy-cross and the unix-port Makefile both depend on.
        #   2. mpy-cross — the bytecode compiler, needed before the port.
        #   3. ports/unix make — the actual unix-port binary.
        run_build_command(
            [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"],
            cwd=source_dir,
        )
        run_build_command(["make", "-C", str(source_dir / "mpy-cross"), jobs])
        # CircuitPython 10.1.4 has a bug in py/py.mk: objringio.c is listed
        # in py.cmake but missing from py.mk.  The workaround disables the
        # RingIO type so the missing object file is not required.
        # See plans/decisions/0017-circuitpython-ringio-bug.md.
        run_build_command(
            [
                "make", "-C", str(source_dir / "ports/unix"),
                f"VARIANT={_UNIX_VARIANT}", jobs,
            ],
            environment=build_environment("-DMICROPY_PY_MICROPYTHON_RINGIO=0"),
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

    print(f"Prepared CircuitPython binary: {binary_file}")
    (TOOLS / "circuitpython.path").write_text(str(binary_file))
    return 0
