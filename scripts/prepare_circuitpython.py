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
which is expected — see ``binary`` below.
"""

from __future__ import annotations

import sys

from shared import (
    RuntimePrep,
    RuntimePrepStep,
    build_environment,
    build_jobs,
    prepare_runtime,
    runtime_versions,
)
from workspace import TOOLS

#: Repository for the CircuitPython upstream source tree.
_REPO_URL = "https://github.com/adafruit/circuitpython.git"

#: Variant subdirectory under ``ports/unix``.
_UNIX_VARIANT = "standard"


def prepare_circuitpython() -> int:
    """Prepare the pinned CircuitPython unix-port runtime inside the workspace."""
    release = runtime_versions()["circuitpython"]["version"]
    source_dir = TOOLS / f"circuitpython-{release}"
    # The CircuitPython unix-port binary is named "micropython" — inherited
    # from the MicroPython fork.  This is expected, not a misconfiguration.
    binary = source_dir / "ports" / "unix" / f"build-{_UNIX_VARIANT}" / "micropython"
    jobs = f"-j{build_jobs()}"

    return prepare_runtime(RuntimePrep(
        label="CircuitPython",
        source_dir=source_dir,
        repo_url=_REPO_URL,
        release=release,
        # CircuitPython's own helper handles submodule + vendored dep fetches.
        init_submodules=(),
        build_steps=(
            # ci_fetch_deps.py fetches git submodules and vendored dependencies
            # that mpy-cross and the unix-port Makefile both depend on.
            RuntimePrepStep(
                [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"],
            ),
            # mpy-cross is the bytecode compiler — required before the port build.
            RuntimePrepStep(["make", "-C", source_dir / "mpy-cross", jobs]),
            # The actual unix-port binary.  Two non-default knobs:
            #
            # 1. ``-DMICROPY_PY_MICROPYTHON_RINGIO=0`` works around a
            #    bug in CP's ``py`` build: in 10.1.4 the file
            #    ``objringio.c`` was listed in ``py.cmake`` but missing
            #    from ``py.mk`` (linker error); 10.2.0 added the .mk
            #    entry but ``objringio.c`` itself still doesn't compile
            #    against CP's diverged ringbuf API.  Disabling the
            #    RingIO type sidesteps both failure modes.  See
            #    ``plans/decisions/0017-circuitpython-ringio-bug.md``.
            #
            # 2. ``MICROPY_PY_SSL=1 MICROPY_SSL_AXTLS=1`` (passed as
            #    Make variables, not CFLAGS — the Makefile blocks that
            #    pull in ``lib/axtls/crypto/sha1.c`` are gated on
            #    Make-level conditionals in ``extmod/extmod.mk``).
            #    Enables ``hashlib.sha1`` + ``hashlib.md5`` (gated on
            #    ``MICROPY_PY_SSL`` in
            #    ``ports/unix/variants/mpconfigvariant_common.h``).
            #
            #    We'd prefer mbedTLS here — every real CP board ships
            #    it, and it's what the CP ``ssl.py`` shim under
            #    ``lib/micropython-lib/python-stdlib/ssl/`` expects
            #    (``import tls``, where ``tls`` is the
            #    ``extmod/modtls_mbedtls.c`` C module).  But CP's
            #    source tree (verified through 10.2.0) has three
            #    independent problems blocking mbedtls on the unix-port,
            #    plus zero downstream test-recovery payoff anyway —
            #    see ``plans/learnings.md`` §"CP unix-port hashlib +
            #    ssl gated on ``MICROPY_PY_SSL`` build flag" for the
            #    full triage.  We live with axtls and the resulting
            #    ``ssl``-module gap on the CP unix-port.
            RuntimePrepStep(
                [
                    "make", "-C", source_dir / "ports/unix",
                    f"VARIANT={_UNIX_VARIANT}", jobs,
                    "MICROPY_PY_SSL=1",
                    "MICROPY_SSL_AXTLS=1",
                ],
                environment=build_environment("-DMICROPY_PY_MICROPYTHON_RINGIO=0"),
            ),
        ),
        expected_binary=binary,
        marker_file=TOOLS / "circuitpython.path",
    ))
