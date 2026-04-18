"""Shared infrastructure helpers — subprocess wrappers, package installation,
runtime preparation, and binary resolution.

This module provides:

- Generic subprocess helpers: :func:`run_command`, :func:`install_command`
- Editable-install logic: :func:`install_editable`
- Build utilities shared by the MicroPython and CircuitPython preparation
  modules: :func:`run_build_command`, :func:`ensure_tool`, :func:`ensure_source_tree`, etc.
- Binary resolution: :func:`resolve_micropython_binary`,
  :func:`resolve_circuitpython_binary`, :func:`resolve_cp_mpy_cross`,
  :func:`resolve_mp_mpy_cross`
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

from workspace import (
    ROOT,
    TOOLS,
    find_publishable_packages,
    find_support_packages,
    read_runtime_versions,
)

# ---------------------------------------------------------------------------
# Generic subprocess helpers
# ---------------------------------------------------------------------------


def run_command(command: list[str], environment: dict[str, str] | None = None) -> int:
    """Run a command from the repository root and return its exit code.

    Args:
        command: Command and arguments to run.
        environment: Optional environment variables to pass to the subprocess.

    Returns:
        Process exit code.
    """
    printable = " ".join(command)
    print(f"+ {printable}")
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


def install_command(python: str | Path | None = None) -> list[str]:
    """Return the pip-install command prefix, preferring uv when available.

    Args:
        python: Interpreter to target.  When *None*, targets the running
            interpreter.  With ``uv`` this becomes ``--python <path>``;
            without ``uv`` it replaces ``sys.executable``.
    """
    if shutil.which("uv"):
        command = ["uv", "pip", "install"]
        if python is not None:
            command.extend(["--python", str(python)])
        return command
    interpreter = str(python) if python is not None else sys.executable
    return [interpreter, "-m", "pip", "install"]


def install_editable(python: str | Path | None = None) -> int:
    """Install all workspace packages as editable.

    Installs publishable libraries (under ``libraries/``) and support
    packages (under ``support/``) so that imports work in any tool
    (editors, debuggers, REPLs, scripts) without manual PYTHONPATH
    setup.  Changes to source files are reflected immediately — no
    reinstall needed.

    Args:
        python: Interpreter to install into.  Defaults to the running
            interpreter when *None*.

    Returns:
        Process exit code (0 on success).
    """
    packages = find_publishable_packages() + find_support_packages()
    if not packages:
        return 0

    editable_args: list[str] = []
    for package in packages:
        editable_args.extend(["-e", package])

    return run_command([*install_command(python), *editable_args])


# ---------------------------------------------------------------------------
# Runtime preparation helpers
# ---------------------------------------------------------------------------


@functools.cache
def runtime_versions() -> dict:
    """Read and cache pinned runtime versions from ``target-runtimes.toml``.

    Lazy — importing :mod:`shared` no longer triggers a TOML read.
    """
    return read_runtime_versions()


def run_build_command(
    command: list[str], cwd: Path | None = None, environment: dict[str, str] | None = None
) -> None:
    """Run a build command and fail fast if it does not succeed.

    Args:
        command: Command and arguments to run.
        cwd: Working directory (defaults to repository root).
        environment: Optional environment variables for the subprocess.
    """
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd or ROOT, env=environment, check=True)


def ensure_tool(name: str) -> None:
    """Require a host tool before attempting to prepare a runtime.

    Args:
        name: Tool binary name to look up on PATH.

    Raises:
        RuntimeError: If the tool is not found.
    """
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def running_on_native_windows() -> bool:
    """Return whether the script is running on native Windows rather than WSL."""
    return os.name == "nt"


def build_jobs() -> str:
    """Return a conservative default parallelism level for local builds."""
    return str(min(os.cpu_count() or 2, 4))


def build_environment(*extra_cflags: str) -> dict[str, str]:
    """Return a copy of ``os.environ`` with additional ``CFLAGS`` flags.

    Flags already present in ``CFLAGS`` are not duplicated.

    Args:
        extra_cflags: Additional compiler flags to append.
    """
    environment = os.environ.copy()
    existing = environment.get("CFLAGS", "").split()
    for flag in extra_cflags:
        if flag not in existing:
            existing.append(flag)
    if existing:
        environment["CFLAGS"] = " ".join(existing)
    return environment


def macos_build_environment() -> dict[str, str]:
    """Return build environment with macOS-specific compiler flags.

    macOS Clang treats ``gnu-folding-constant`` as an error by default,
    which breaks the MicroPython build.  This helper adds the suppression
    flag when running on Darwin.  Not needed on Linux/GCC.
    """
    macos_flags = ["-Wno-error=gnu-folding-constant"] if sys.platform == "darwin" else []
    return build_environment(*macos_flags)


def ensure_source_tree(
    source_dir: Path,
    repo_url: str,
    release: str,
    *,
    init_submodules: bool = False,
) -> None:
    """Clone a pinned source tree if not already present.

    Args:
        source_dir: Target directory for the cloned repository.
        repo_url: Git repository URL to clone.
        release: Git tag or branch to check out.
        init_submodules: Whether to recursively initialize submodules after
            cloning.
    """
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", release, repo_url, str(source_dir),
        ])
    if init_submodules:
        run_build_command(
            ["git", "submodule", "update", "--init", "--recursive"], cwd=source_dir
        )


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _read_prepared_binary(marker_name: str) -> str | None:
    """Read a binary path from a marker file written by a prepare step.

    The prepare-micropython and prepare-circuitpython scripts write the
    absolute path of the compiled binary to a marker file (e.g.
    ``.tools/micropython.path``) so other commands can find it without
    recompiling.
    """
    marker_file = TOOLS / marker_name
    if not marker_file.exists():
        return None
    candidate_file = Path(marker_file.read_text().strip())
    if candidate_file.exists():
        return str(candidate_file)
    return None


def resolve_micropython_binary(binary: str | None = None) -> str | None:
    """Resolve a MicroPython binary from an explicit path, repository-local tools, or PATH.

    Resolution order (first match wins):
      1. *binary* — explicit override from CLI (``--micropython-binary``).
      2. Marker file from ``prepare-micropython`` — local repository-managed build.
      3. System PATH lookup — globally installed binary as last resort.

    Raises :class:`SystemExit` if *binary* is given but does not exist.
    """
    if binary:
        if not Path(binary).exists():
            print(f"MicroPython binary not found: {binary}")
            raise SystemExit(1)
        return binary
    prepared = _read_prepared_binary("micropython.path")
    if prepared:
        return prepared
    return shutil.which("micropython")


def resolve_circuitpython_binary(binary: str | None = None) -> str | None:
    """Resolve a CircuitPython binary from an explicit path, repository-local tools, or PATH.

    Resolution order (first match wins):
      1. *binary* — explicit override from CLI (``--circuitpython-binary``).
      2. Marker file from ``prepare-circuitpython`` — local repository-managed build.
      3. System PATH lookup — globally installed binary as last resort.

    Raises :class:`SystemExit` if *binary* is given but does not exist.
    """
    if binary:
        if not Path(binary).exists():
            print(f"CircuitPython binary not found: {binary}")
            raise SystemExit(1)
        return binary
    prepared = _read_prepared_binary("circuitpython.path")
    if prepared:
        return prepared
    return shutil.which("circuitpython")


# ---------------------------------------------------------------------------
# mpy-cross resolution
# ---------------------------------------------------------------------------


def resolve_cp_mpy_cross(binary: str | None = None) -> str | None:
    """Resolve CircuitPython's mpy-cross from an explicit path or the prepared source tree.

    Resolution order (first match wins):
      1. *binary* — explicit override from CLI (``--cp-mpy-cross``).
      2. Prepared source tree — ``.tools/circuitpython-{version}/mpy-cross/build/mpy-cross``
         where *version* comes from ``target-runtimes.toml``.

    No PATH fallback — CircuitPython's mpy-cross is not pip-installable.
    Raises :class:`SystemExit` if *binary* is given but does not exist.

    Args:
        binary: Explicit path to the mpy-cross binary, or ``None`` for
            auto-discovery.
    """
    if binary:
        if not Path(binary).exists():
            print(f"CircuitPython mpy-cross not found: {binary}")
            raise SystemExit(1)
        return binary
    cp_version = runtime_versions().get("circuitpython", {}).get("version")
    if cp_version:
        candidate = TOOLS / f"circuitpython-{cp_version}" / "mpy-cross" / "build" / "mpy-cross"
        if candidate.exists():
            return str(candidate)
    return None


def resolve_mp_mpy_cross(binary: str | None = None) -> str | None:
    """Resolve MicroPython's mpy-cross from an explicit path, prepared tree, or PATH.

    Resolution order (first match wins):
      1. *binary* — explicit override from CLI (``--mp-mpy-cross``).
      2. Prepared source tree — ``.tools/micropython-{version}/mpy-cross/build/mpy-cross``
         where *version* comes from ``target-runtimes.toml``.
      3. System PATH lookup — pip-installed ``mpy-cross``.

    Raises :class:`SystemExit` if *binary* is given but does not exist.

    Args:
        binary: Explicit path to the mpy-cross binary, or ``None`` for
            auto-discovery.
    """
    if binary:
        if not Path(binary).exists():
            print(f"MicroPython mpy-cross not found: {binary}")
            raise SystemExit(1)
        return binary
    mp_version = runtime_versions().get("micropython", {}).get("version")
    if mp_version:
        candidate = TOOLS / f"micropython-{mp_version}" / "mpy-cross" / "build" / "mpy-cross"
        if candidate.exists():
            return str(candidate)
    return shutil.which("mpy-cross")
