"""Prepare a repo-local CircuitPython unix-port runtime for compatibility tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIRCUITPYTHON_RELEASE = "10.1.4"
CIRCUITPYTHON_REPOSITORY_URL = "https://github.com/adafruit/circuitpython.git"
SOURCE_DIR = ROOT / ".tools" / f"circuitpython-{CIRCUITPYTHON_RELEASE}"
UNIX_VARIANT = "standard"
DEFAULT_BINARY_PATH = SOURCE_DIR / "ports" / "unix" / f"build-{UNIX_VARIANT}" / "micropython"


def _run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Run a preparation command and fail fast if it does not succeed."""
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd or ROOT, env=env, check=True)


def _ensure_tool(name: str) -> None:
    """Require a host tool before attempting to prepare the runtime."""
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def _running_on_native_windows() -> bool:
    """Return whether the script is running on native Windows rather than WSL."""
    return os.name == "nt"


def _build_jobs() -> str:
    """Return a conservative default parallelism level for the local build."""
    return str(min(os.cpu_count() or 2, 4))


def _build_env() -> dict[str, str]:
    """Return environment variables for the local CircuitPython unix build.

    These flags are currently the smallest verified local workaround set for the
    pinned `10.1.4` unix-port build in this workspace:

    - `-DMP3DEC_GENERIC` avoids the MP3 decoder's platform guard failing on the
      unix-port build host.
    - `-DMICROPY_PY_MICROPYTHON_RINGIO=0` keeps the selected unix variant aligned
      with the linked core objects for the local smoke-test build.
    - `-Wno-typedef-redefinition` is only added on macOS to tolerate a local
      typedef redefinition warning that otherwise becomes a hard error.

    Keep this list minimal and only document flags that have been verified from
    an actual local build failure and rerun.
    """
    env = os.environ.copy()
    flags = env.get("CFLAGS_EXTRA", "").split()

    required_flags = [
        "-DMP3DEC_GENERIC",
        "-DMICROPY_PY_MICROPYTHON_RINGIO=0",
    ]
    if sys.platform == "darwin":
        required_flags.append("-Wno-typedef-redefinition")

    for flag in required_flags:
        if flag not in flags:
            flags.append(flag)

    env["CFLAGS_EXTRA"] = " ".join(flags)
    return env


def _ensure_source_tree() -> None:
    """Clone the pinned CircuitPython source tree if it is not already present."""
    SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)

    if not SOURCE_DIR.exists():
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                CIRCUITPYTHON_RELEASE,
                CIRCUITPYTHON_REPOSITORY_URL,
                str(SOURCE_DIR),
            ]
        )


def prepare_circuitpython() -> int:
    """Prepare the pinned CircuitPython unix-port runtime inside the workspace."""
    if _running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-circuitpython` and unix-port validation."
        )
        return 2

    for tool_name in ("git", "make", "cc"):
        _ensure_tool(tool_name)

    _ensure_source_tree()

    jobs = f"-j{_build_jobs()}"
    _run([sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"], cwd=SOURCE_DIR)
    _run(["make", "-C", str(SOURCE_DIR / "mpy-cross"), jobs])
    _run(
        ["make", "-C", str(SOURCE_DIR / "ports/unix"), f"VARIANT={UNIX_VARIANT}", jobs],
        env=_build_env(),
    )

    if not DEFAULT_BINARY_PATH.exists():
        print(f"Prepared source tree does not contain the expected binary: {DEFAULT_BINARY_PATH}")
        return 1

    print(f"Prepared CircuitPython binary: {DEFAULT_BINARY_PATH}")
    return 0


def main() -> int:
    """Prepare the repo-local CircuitPython runtime and return a shell-style exit code."""
    try:
        return prepare_circuitpython()
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

