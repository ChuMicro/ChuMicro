"""Build mpy-cross compilers for CircuitPython and MicroPython.

Clones the pinned runtime source trees (versions from
``target-runtimes.toml``) into ``.tools/`` and compiles only the
mpy-cross bytecode compilers, not the full unix-port binaries.  This is
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

import sys

from repo_layout import TOOLS
from shared import (
    RuntimePrep,
    RuntimePrepStep,
    build_jobs,
    macos_build_environment,
    prepare_runtime,
    runtime_versions,
)

_CP_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_MP_REPO_URL = "https://github.com/micropython/micropython.git"


def prepare_mpy_cross() -> int:
    """Build mpy-cross compilers for both CircuitPython and MicroPython.

    Skips each runtime's build if the mpy-cross binary already exists
    (cache-friendly).  Does NOT build the full unix-port interpreters.
    Use ``prepare-micropython`` / ``prepare-circuitpython`` for that.
    """
    jobs = f"-j{build_jobs()}"
    environment = macos_build_environment()

    # MicroPython mpy-cross.
    mp_version = runtime_versions()["micropython"]["version"]
    mp_source_dir = TOOLS / f"micropython-{mp_version}"
    mp_mpy_cross = mp_source_dir / "mpy-cross" / "build" / "mpy-cross"
    if mp_mpy_cross.exists():
        print(f"MicroPython mpy-cross already built: {mp_mpy_cross}")
    else:
        print("Building MicroPython mpy-cross...")
        result = prepare_runtime(RuntimePrep(
            label="MicroPython mpy-cross",
            source_dir=mp_source_dir,
            repo_url=_MP_REPO_URL,
            release=mp_version,
            build_steps=(
                RuntimePrepStep(
                    ["make", "-C", mp_source_dir / "mpy-cross", jobs],
                    environment=environment,
                ),
            ),
            expected_binary=mp_mpy_cross,
        ))
        if result != 0:
            return result

    # CircuitPython mpy-cross.
    cp_version = runtime_versions()["circuitpython"]["version"]
    cp_source_dir = TOOLS / f"circuitpython-{cp_version}"
    cp_mpy_cross = cp_source_dir / "mpy-cross" / "build" / "mpy-cross"
    if cp_mpy_cross.exists():
        print(f"CircuitPython mpy-cross already built: {cp_mpy_cross}")
    else:
        print("Building CircuitPython mpy-cross...")
        result = prepare_runtime(RuntimePrep(
            label="CircuitPython mpy-cross",
            source_dir=cp_source_dir,
            repo_url=_CP_REPO_URL,
            release=cp_version,
            build_steps=(
                # ci_fetch_deps.py fetches git submodules and vendored
                # dependencies that the mpy-cross Makefile needs.
                RuntimePrepStep(
                    [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross"],
                ),
                RuntimePrepStep(
                    ["make", "-C", cp_source_dir / "mpy-cross", jobs],
                    environment=environment,
                ),
            ),
            expected_binary=cp_mpy_cross,
        ))
        if result != 0:
            return result

    return 0
