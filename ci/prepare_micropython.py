"""Prepare a repo-local MicroPython unix-port runtime for compatibility tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

with (ROOT / "runtime-versions.toml").open("rb") as _f:
    _versions = tomllib.load(_f)

MICROPYTHON_RELEASE = _versions["micropython"]["version"]
MICROPYTHON_REPOSITORY_URL = "https://github.com/micropython/micropython.git"
SOURCE_DIR = ROOT / ".tools" / f"micropython-{MICROPYTHON_RELEASE}"
DEFAULT_BINARY_PATH = SOURCE_DIR / "ports" / "unix" / "build-standard" / "micropython"


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
    """Return environment variables for the MicroPython build."""
    env = os.environ.copy()

    if sys.platform == "darwin":
        flag = "-Wno-error=gnu-folding-constant"
        existing_flags = env.get("CFLAGS_EXTRA", "").split()
        if flag not in existing_flags:
            existing_flags.append(flag)
            env["CFLAGS_EXTRA"] = " ".join(existing_flags)

    return env


def _ensure_source_tree() -> None:
    """Clone the pinned MicroPython source tree if it is not already present."""
    SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)

    if not SOURCE_DIR.exists():
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                MICROPYTHON_RELEASE,
                MICROPYTHON_REPOSITORY_URL,
                str(SOURCE_DIR),
            ]
        )

    _run(["git", "submodule", "update", "--init", "--recursive"], cwd=SOURCE_DIR)


def prepare_micropython() -> int:
    """Prepare the pinned MicroPython unix-port runtime inside the workspace."""
    if _running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-micropython` and unix-port validation."
        )
        return 2

    for tool_name in ("git", "make", "cc"):
        _ensure_tool(tool_name)

    _ensure_source_tree()

    jobs = f"-j{_build_jobs()}"
    _run(["make", "-C", str(SOURCE_DIR / "mpy-cross"), jobs], env=_build_env())
    _run(["make", "-C", str(SOURCE_DIR / "ports/unix"), jobs], env=_build_env())

    if not DEFAULT_BINARY_PATH.exists():
        print(f"Prepared source tree does not contain the expected binary: {DEFAULT_BINARY_PATH}")
        return 1

    print(f"Prepared MicroPython binary: {DEFAULT_BINARY_PATH}")
    (ROOT / ".tools" / "micropython.path").write_text(str(DEFAULT_BINARY_PATH))
    return 0


def main() -> int:
    """Prepare the repo-local MicroPython runtime and return a shell-style exit code."""
    try:
        return prepare_micropython()
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

