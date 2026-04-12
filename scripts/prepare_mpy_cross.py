"""Build mpy-cross compilers for CircuitPython and MicroPython.

Clones the pinned runtime source trees (versions from
``target-runtimes.toml``) into ``.tools/`` and compiles only the
mpy-cross bytecode compilers — not the full unix-port binaries.  This is
significantly faster than ``prepare-micropython`` /
``prepare-circuitpython`` and is all the release and promote workflows
need for bundle staging.

The built binaries are discoverable by ``resolve_cp_mpy_cross()`` and
``resolve_mp_mpy_cross()`` in ``shared.py`` via the standard ``.tools/``
directory layout:

- ``.tools/micropython-{version}/mpy-cross/build/mpy-cross``
- ``.tools/circuitpython-{version}/mpy-cross/build/mpy-cross``

Prerequisites: ``git``, ``make``, and a C compiler (``cc``) on PATH.

Usage (via task runner)::

    python scripts/run.py prepare-mpy-cross
"""

from __future__ import annotations

import subprocess
import sys

from shared import (
    build_jobs,
    ensure_source_tree,
    ensure_tool,
    macos_build_environment,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)
from workspace import TOOLS

_CP_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_MP_REPO_URL = "https://github.com/micropython/micropython.git"


def _cp_source_dir():
    """Return the CircuitPython source directory (computed lazily)."""
    cp_version = runtime_versions()["circuitpython"]["version"]
    return TOOLS / f"circuitpython-{cp_version}"


def _mp_source_dir():
    """Return the MicroPython source directory (computed lazily)."""
    mp_version = runtime_versions()["micropython"]["version"]
    return TOOLS / f"micropython-{mp_version}"


def _cp_mpy_cross():
    """Return the expected CircuitPython mpy-cross path (computed lazily)."""
    return _cp_source_dir() / "mpy-cross" / "build" / "mpy-cross"


def _mp_mpy_cross():
    """Return the expected MicroPython mpy-cross path (computed lazily)."""
    return _mp_source_dir() / "mpy-cross" / "build" / "mpy-cross"


def prepare_mpy_cross() -> int:
    """Build mpy-cross compilers for both CircuitPython and MicroPython.

    Skips each runtime's build if the mpy-cross binary already exists
    (cache-friendly).  Does NOT build the full unix-port interpreters —
    use ``prepare-micropython`` / ``prepare-circuitpython`` for that.
    """
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-mpy-cross`."
        )
        return 2

    try:
        for tool_name in ("git", "make", "cc"):
            ensure_tool(tool_name)

        jobs = f"-j{build_jobs()}"
        environment = macos_build_environment()

        # --- MicroPython mpy-cross ---
        mp_mpy_cross = _mp_mpy_cross()
        if mp_mpy_cross.exists():
            print(f"MicroPython mpy-cross already built: {mp_mpy_cross}")
        else:
            print("Building MicroPython mpy-cross...")
            mp_source_dir = _mp_source_dir()
            mp_version = runtime_versions()["micropython"]["version"]
            ensure_source_tree(mp_source_dir, _MP_REPO_URL, mp_version)
            run_build_command(
                ["make", "-C", str(mp_source_dir / "mpy-cross"), jobs],
                environment=environment,
            )
            if not mp_mpy_cross.exists():
                print(
                    f"MicroPython mpy-cross build did not produce "
                    f"expected binary: {mp_mpy_cross}"
                )
                return 1
            print(f"Built MicroPython mpy-cross: {mp_mpy_cross}")

        # --- CircuitPython mpy-cross ---
        cp_mpy_cross = _cp_mpy_cross()
        if cp_mpy_cross.exists():
            print(f"CircuitPython mpy-cross already built: {cp_mpy_cross}")
        else:
            print("Building CircuitPython mpy-cross...")
            cp_source_dir = _cp_source_dir()
            cp_version = runtime_versions()["circuitpython"]["version"]
            ensure_source_tree(cp_source_dir, _CP_REPO_URL, cp_version)
            # CircuitPython's ci_fetch_deps.py fetches the git submodules
            # and vendored dependencies that the mpy-cross Makefile needs.
            run_build_command(
                [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross"],
                cwd=cp_source_dir,
            )
            run_build_command(
                ["make", "-C", str(cp_source_dir / "mpy-cross"), jobs],
                environment=environment,
            )
            if not cp_mpy_cross.exists():
                print(
                    f"CircuitPython mpy-cross build did not produce "
                    f"expected binary: {cp_mpy_cross}"
                )
                return 1
            print(f"Built CircuitPython mpy-cross: {cp_mpy_cross}")

    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    return 0

