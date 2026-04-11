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
    build_environment,
    build_jobs,
    ensure_tool,
    run_build_command,
    running_on_native_windows,
    runtime_versions,
)
from workspace import TOOLS

_VERSIONS = runtime_versions()
_CP_VERSION = _VERSIONS["circuitpython"]["version"]
_MP_VERSION = _VERSIONS["micropython"]["version"]

_CP_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_MP_REPO_URL = "https://github.com/micropython/micropython.git"

_CP_SOURCE_DIR = TOOLS / f"circuitpython-{_CP_VERSION}"
_MP_SOURCE_DIR = TOOLS / f"micropython-{_MP_VERSION}"

_CP_MPY_CROSS = _CP_SOURCE_DIR / "mpy-cross" / "build" / "mpy-cross"
_MP_MPY_CROSS = _MP_SOURCE_DIR / "mpy-cross" / "build" / "mpy-cross"


def _ensure_micropython_source() -> None:
    """Clone the pinned MicroPython source tree if not already present."""
    _MP_SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _MP_SOURCE_DIR.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", _MP_VERSION, _MP_REPO_URL, str(_MP_SOURCE_DIR),
        ])


def _ensure_circuitpython_source() -> None:
    """Clone the pinned CircuitPython source tree if not already present."""
    _CP_SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _CP_SOURCE_DIR.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", _CP_VERSION, _CP_REPO_URL, str(_CP_SOURCE_DIR),
        ])


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
        # macOS Clang treats gnu-folding-constant as an error by default,
        # which breaks the MicroPython build.  Not needed on Linux/GCC.
        macos_flags = (
            ["-Wno-error=gnu-folding-constant"]
            if sys.platform == "darwin"
            else []
        )
        environment = build_environment(*macos_flags)

        # --- MicroPython mpy-cross ---
        if _MP_MPY_CROSS.exists():
            print(f"MicroPython mpy-cross already built: {_MP_MPY_CROSS}")
        else:
            print("Building MicroPython mpy-cross...")
            _ensure_micropython_source()
            run_build_command(
                ["make", "-C", str(_MP_SOURCE_DIR / "mpy-cross"), jobs],
                environment=environment,
            )
            if not _MP_MPY_CROSS.exists():
                print(
                    f"MicroPython mpy-cross build did not produce "
                    f"expected binary: {_MP_MPY_CROSS}"
                )
                return 1
            print(f"Built MicroPython mpy-cross: {_MP_MPY_CROSS}")

        # --- CircuitPython mpy-cross ---
        if _CP_MPY_CROSS.exists():
            print(f"CircuitPython mpy-cross already built: {_CP_MPY_CROSS}")
        else:
            print("Building CircuitPython mpy-cross...")
            _ensure_circuitpython_source()
            # CircuitPython's ci_fetch_deps.py fetches the git submodules
            # and vendored dependencies that the mpy-cross Makefile needs.
            run_build_command(
                [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross"],
                cwd=_CP_SOURCE_DIR,
            )
            run_build_command(
                ["make", "-C", str(_CP_SOURCE_DIR / "mpy-cross"), jobs],
                environment=environment,
            )
            if not _CP_MPY_CROSS.exists():
                print(
                    f"CircuitPython mpy-cross build did not produce "
                    f"expected binary: {_CP_MPY_CROSS}"
                )
                return 1
            print(f"Built CircuitPython mpy-cross: {_CP_MPY_CROSS}")

    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    return 0

