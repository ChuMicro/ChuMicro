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

from discovery import TOOLS
from prepare import (
    build_env,
    build_jobs,
    ensure_tool,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)

_RELEASE = runtime_versions()["circuitpython"]["version"]
_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_SOURCE_DIR = TOOLS / f"circuitpython-{_RELEASE}"
_UNIX_VARIANT = "standard"
# The CircuitPython unix-port binary is named "micropython" — inherited
# from the MicroPython fork.  This is expected, not a misconfiguration.
_BINARY_FILE = _SOURCE_DIR / "ports" / "unix" / f"build-{_UNIX_VARIANT}" / "micropython"


def _ensure_source_tree() -> None:
    """Clone the pinned CircuitPython source tree if it is not already present."""
    _SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _SOURCE_DIR.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", _RELEASE, _REPO_URL, str(_SOURCE_DIR),
        ])


def prepare_circuitpython() -> int:
    """Prepare the pinned CircuitPython unix-port runtime inside the workspace."""
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-circuitpython` and unix-port validation."
        )
        return 2

    try:
        for tool_name in ("git", "make", "cc"):
            ensure_tool(tool_name)

        _ensure_source_tree()

        jobs = f"-j{build_jobs()}"
        # Build steps must run in this exact order:
        #   1. ci_fetch_deps.py — fetches git submodules and vendored dependencies
        #      that mpy-cross and the unix-port Makefile both depend on.
        #   2. mpy-cross — the bytecode compiler, needed before the port.
        #   3. ports/unix make — the actual unix-port binary.
        run_build_command(
            [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"],
            cwd=_SOURCE_DIR,
        )
        run_build_command(["make", "-C", str(_SOURCE_DIR / "mpy-cross"), jobs])
        # CircuitPython 10.1.4 has a bug in py/py.mk: objringio.c is listed
        # in py.cmake but missing from py.mk.  The workaround disables the
        # RingIO type so the missing object file is not required.
        # See plans/decisions/0017-circuitpython-ringio-bug.md.
        run_build_command(
            [
                "make", "-C", str(_SOURCE_DIR / "ports/unix"),
                f"VARIANT={_UNIX_VARIANT}", jobs,
            ],
            env=build_env("-DMICROPY_PY_MICROPYTHON_RINGIO=0"),
        )
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _BINARY_FILE.exists():
        print(f"Prepared source tree does not contain the expected binary: {_BINARY_FILE}")
        return 1

    print(f"Prepared CircuitPython binary: {_BINARY_FILE}")
    (TOOLS / "circuitpython.path").write_text(str(_BINARY_FILE))
    return 0
