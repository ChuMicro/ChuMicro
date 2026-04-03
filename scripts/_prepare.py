"""Runtime preparation and binary resolution for MicroPython and CircuitPython.

Provides ``prepare_micropython()`` and ``prepare_circuitpython()`` for
building pinned unix-port runtimes under ``.tools/``, plus binary
resolution helpers.  Called directly by ``scripts/run.py`` tasks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from _discovery import ROOT, TOOLS, read_runtime_versions

_versions = read_runtime_versions()

# --- MicroPython constants ---

_MP_RELEASE = _versions["micropython"]["version"]
_MP_REPO_URL = "https://github.com/micropython/micropython.git"
_MP_SOURCE_DIR = TOOLS / f"micropython-{_MP_RELEASE}"
_MP_BINARY = _MP_SOURCE_DIR / "ports" / "unix" / "build-standard" / "micropython"

# --- CircuitPython constants ---

_CP_RELEASE = _versions["circuitpython"]["version"]
_CP_REPO_URL = "https://github.com/adafruit/circuitpython.git"
_CP_SOURCE_DIR = TOOLS / f"circuitpython-{_CP_RELEASE}"
_CP_UNIX_VARIANT = "standard"
_CP_BINARY = _CP_SOURCE_DIR / "ports" / "unix" / f"build-{_CP_UNIX_VARIANT}" / "micropython"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_cmd(
    command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run a build command and fail fast if it does not succeed."""
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd or ROOT, env=env, check=True)


def _ensure_tool(name: str) -> None:
    """Require a host tool before attempting to prepare a runtime."""
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def _running_on_native_windows() -> bool:
    """Return whether the script is running on native Windows rather than WSL."""
    return os.name == "nt"


def _build_jobs() -> str:
    """Return a conservative default parallelism level for local builds."""
    return str(min(os.cpu_count() or 2, 4))


# ---------------------------------------------------------------------------
# MicroPython preparation
# ---------------------------------------------------------------------------


def _mp_build_env() -> dict[str, str]:
    """Return environment variables for the MicroPython build."""
    env = os.environ.copy()
    if sys.platform == "darwin":
        flag = "-Wno-error=gnu-folding-constant"
        existing = env.get("CFLAGS_EXTRA", "").split()
        if flag not in existing:
            existing.append(flag)
            env["CFLAGS_EXTRA"] = " ".join(existing)
    return env


def _mp_ensure_source_tree() -> None:
    """Clone the pinned MicroPython source tree if it is not already present."""
    _MP_SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _MP_SOURCE_DIR.exists():
        _run_cmd([
            "git", "clone", "--depth", "1",
            "--branch", _MP_RELEASE, _MP_REPO_URL, str(_MP_SOURCE_DIR),
        ])
    _run_cmd(
        ["git", "submodule", "update", "--init", "--recursive"], cwd=_MP_SOURCE_DIR
    )


def prepare_micropython() -> int:
    """Prepare the pinned MicroPython unix-port runtime inside the workspace."""
    if _running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-micropython` and unix-port validation."
        )
        return 2

    try:
        for tool_name in ("git", "make", "cc"):
            _ensure_tool(tool_name)

        _mp_ensure_source_tree()

        jobs = f"-j{_build_jobs()}"
        env = _mp_build_env()
        _run_cmd(["make", "-C", str(_MP_SOURCE_DIR / "mpy-cross"), jobs], env=env)
        _run_cmd(["make", "-C", str(_MP_SOURCE_DIR / "ports/unix"), jobs], env=env)
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _MP_BINARY.exists():
        print(f"Prepared source tree does not contain the expected binary: {_MP_BINARY}")
        return 1

    print(f"Prepared MicroPython binary: {_MP_BINARY}")
    (TOOLS / "micropython.path").write_text(str(_MP_BINARY))
    return 0


# ---------------------------------------------------------------------------
# CircuitPython preparation
# ---------------------------------------------------------------------------


def _cp_build_env() -> dict[str, str]:
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


def _cp_ensure_source_tree() -> None:
    """Clone the pinned CircuitPython source tree if it is not already present."""
    _CP_SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not _CP_SOURCE_DIR.exists():
        _run_cmd([
            "git", "clone", "--depth", "1",
            "--branch", _CP_RELEASE, _CP_REPO_URL, str(_CP_SOURCE_DIR),
        ])


def prepare_circuitpython() -> int:
    """Prepare the pinned CircuitPython unix-port runtime inside the workspace."""
    if _running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for `prepare-circuitpython` and unix-port validation."
        )
        return 2

    try:
        for tool_name in ("git", "make", "cc"):
            _ensure_tool(tool_name)

        _cp_ensure_source_tree()

        jobs = f"-j{_build_jobs()}"
        _run_cmd(
            [sys.executable, "tools/ci_fetch_deps.py", "mpy-cross", "tests"],
            cwd=_CP_SOURCE_DIR,
        )
        _run_cmd(["make", "-C", str(_CP_SOURCE_DIR / "mpy-cross"), jobs])
        _run_cmd(
            [
                "make", "-C", str(_CP_SOURCE_DIR / "ports/unix"),
                f"VARIANT={_CP_UNIX_VARIANT}", jobs,
            ],
            env=_cp_build_env(),
        )
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if not _CP_BINARY.exists():
        print(f"Prepared source tree does not contain the expected binary: {_CP_BINARY}")
        return 1

    print(f"Prepared CircuitPython binary: {_CP_BINARY}")
    (TOOLS / "circuitpython.path").write_text(str(_CP_BINARY))
    return 0


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _read_prepared_binary(marker_name: str) -> str | None:
    """Read a binary path from a marker file written by a prepare step."""
    marker = TOOLS / marker_name
    if not marker.exists():
        return None
    candidate = Path(marker.read_text().strip())
    if candidate.exists():
        return str(candidate)
    return None


def resolve_micropython_binary() -> str | None:
    """Resolve a MicroPython binary from env vars, repo-local tools, or PATH."""
    configured = os.environ.get("MICROPYTHON_BIN")
    if configured:
        return configured
    prepared = _read_prepared_binary("micropython.path")
    if prepared:
        return prepared
    return shutil.which("micropython")


def resolve_circuitpython_binary() -> str | None:
    """Resolve a CircuitPython binary from env vars, repo-local tools, or PATH."""
    configured = os.environ.get("CIRCUITPYTHON_BIN")
    if configured:
        return configured
    prepared = _read_prepared_binary("circuitpython.path")
    if prepared:
        return prepared
    return shutil.which("circuitpython")


