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

from repo_layout import TOOLS
from shared import (
    RuntimePrep,
    RuntimePrepStep,
    build_jobs,
    macos_build_environment,
    prepare_runtime,
    runtime_versions,
)

#: Repository for the MicroPython upstream source tree.
_REPO_URL = "https://github.com/micropython/micropython.git"

#: Submodules required for the unix-port build.  Recursive submodule
#: init pulls ~1.4 GB of board-specific libraries (stm32lib, pico-sdk,
#: nxp_driver, etc.) that the unix-port never uses.
_UNIX_PORT_SUBMODULES = (
    "lib/berkeley-db-1.xx",
    "lib/libffi",
    "lib/mbedtls",
    "lib/micropython-lib",
)


def prepare_micropython() -> int:
    """Prepare the pinned MicroPython unix-port runtime inside the workspace."""
    release = runtime_versions()["micropython"]["version"]
    source_dir = TOOLS / f"micropython-{release}"
    binary = source_dir / "ports" / "unix" / "build-standard" / "micropython"
    jobs = f"-j{build_jobs()}"
    environment = macos_build_environment()

    return prepare_runtime(RuntimePrep(
        label="MicroPython",
        source_dir=source_dir,
        repo_url=_REPO_URL,
        release=release,
        init_submodules=_UNIX_PORT_SUBMODULES,
        build_steps=(
            # mpy-cross is the bytecode compiler — required before the port build.
            RuntimePrepStep(
                ["make", "-C", source_dir / "mpy-cross", jobs],
                environment=environment,
            ),
            # The actual unix-port interpreter binary.
            RuntimePrepStep(
                ["make", "-C", source_dir / "ports/unix", jobs],
                environment=environment,
            ),
        ),
        expected_binary=binary,
        marker_file=TOOLS / "micropython.path",
    ))
