"""Shared runtime preparation helpers and binary resolution.

This module provides build utilities shared by the MicroPython and
CircuitPython preparation modules, plus binary resolution functions
used by the task runner.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

from discovery import ROOT, TOOLS, read_runtime_versions


@functools.cache
def runtime_versions() -> dict:
    """Read and cache pinned runtime versions from ``target-runtimes.toml``.

    Lazy — importing :mod:`prepare` no longer triggers a TOML read.
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


def build_env(*extra_cflags: str) -> dict[str, str]:
    """Return a copy of ``os.environ`` with additional ``CFLAGS_EXTRA`` flags.

    Flags already present in ``CFLAGS_EXTRA`` are not duplicated.

    Args:
        extra_cflags: Additional compiler flags to append.
    """
    environment = os.environ.copy()
    existing = environment.get("CFLAGS_EXTRA", "").split()
    for flag in extra_cflags:
        if flag not in existing:
            existing.append(flag)
    if existing:
        environment["CFLAGS_EXTRA"] = " ".join(existing)
    return environment


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
