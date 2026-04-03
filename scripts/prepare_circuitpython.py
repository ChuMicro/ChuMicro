"""CircuitPython unix-port preparation."""

from __future__ import annotations

import os
import subprocess
import sys

from discovery import TOOLS
from prepare import VERSIONS, build_jobs, ensure_tool, run_build_command, running_on_native_windows

_RELEASE = VERSIONS["circuitpython"]["version"]
_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_SOURCE_DIR = TOOLS / f"circuitpython-{_RELEASE}"
_UNIX_VARIANT = "standard"
_BINARY = _SOURCE_DIR / "ports" / "unix" / f"build-{_UNIX_VARIANT}" / "micropython"


def _build_env() -> dict[str, str]:
    """Return environment variables for the local CircuitPython unix build.

    These flags are currently the smallest verified local workaround set for the
    pinned ``10.1.4`` unix-port build in this workspace:

    - ``-DMP3DEC_GENERIC`` avoids the MP3 decoder's platform guard failing on the
      unix-port build host.
    - ``-DMICROPY_PY_MICROPYTHON_RINGIO=0`` keeps the selected unix variant aligned
      with the linked core objects for the local smoke-test build.
    - ``-Wno-typedef-redefinition`` is only added on macOS to tolerate a local
      typedef redefinition warning that otherwise becomes a hard error.

    Keep this list minimal and only document flags that have been verified from
    an actual local build failure and rerun.
    """
    env = os.environ.copy()
    flags = env.get("CFLAGS_EXTRA", "").split()
    required = ["-DMP3DEC_GENERIC", "-DMICROPY_PY_MICROPYTHON_RINGIO=0"]
    if sys.platform == "darwin":
        required.append("-Wno-typedef-redefinition")
    for flag in required:
        if flag not in flags:
            flags.append(flag)
    env["CFLAGS_EXTRA"] = " ".join(flags)
    return env


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
        run_build_command(
            [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"],
            cwd=_SOURCE_DIR,
        )
        run_build_command(["make", "-C", str(_SOURCE_DIR / "mpy-cross"), jobs])
        run_build_command(
            [
                "make", "-C", str(_SOURCE_DIR / "ports/unix"),
                f"VARIANT={_UNIX_VARIANT}", jobs,
            ],
            env=_build_env(),
        )
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _BINARY.exists():
        print(f"Prepared source tree does not contain the expected binary: {_BINARY}")
        return 1

    print(f"Prepared CircuitPython binary: {_BINARY}")
    (TOOLS / "circuitpython.path").write_text(str(_BINARY))
    return 0

