"""MicroPython unix-port preparation."""

from __future__ import annotations

import os
import subprocess
import sys

from discovery import TOOLS
from prepare import VERSIONS, build_jobs, ensure_tool, run_build_command, running_on_native_windows

_RELEASE = VERSIONS["micropython"]["version"]
_REPO_URL = "https://github.com/micropython/micropython.git"
_SOURCE_DIR = TOOLS / f"micropython-{_RELEASE}"
_BINARY = _SOURCE_DIR / "ports" / "unix" / "build-standard" / "micropython"


def _build_env() -> dict[str, str]:
    """Return environment variables for the MicroPython build."""
    env = os.environ.copy()
    # macOS Clang treats gnu-folding-constant as an error by default,
    # which breaks the MicroPython build.  Suppress it here so the
    # build succeeds.  Not needed on Linux/GCC.
    if sys.platform == "darwin":
        flag = "-Wno-error=gnu-folding-constant"
        existing = env.get("CFLAGS_EXTRA", "").split()
        if flag not in existing:
            existing.append(flag)
            env["CFLAGS_EXTRA"] = " ".join(existing)
    return env


def _ensure_source_tree() -> None:
    """Clone the pinned MicroPython source tree if it is not already present."""
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
        env = _build_env()
        run_build_command(["make", "-C", str(_SOURCE_DIR / "mpy-cross"), jobs], env=env)
        run_build_command(["make", "-C", str(_SOURCE_DIR / "ports/unix"), jobs], env=env)
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _BINARY.exists():
        print(f"Prepared source tree does not contain the expected binary: {_BINARY}")
        return 1

    print(f"Prepared MicroPython binary: {_BINARY}")
    (TOOLS / "micropython.path").write_text(str(_BINARY))
    return 0
