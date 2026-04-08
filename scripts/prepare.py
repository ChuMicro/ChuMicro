"""Shared runtime preparation helpers and binary resolution.

This module provides build utilities shared by the MicroPython and
CircuitPython preparation modules, plus binary resolution functions
used by the task runner.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from discovery import ROOT, TOOLS, read_runtime_versions

VERSIONS = read_runtime_versions()


def run_build_command(
    command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run a build command and fail fast if it does not succeed."""
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd or ROOT, env=env, check=True)


def ensure_tool(name: str) -> None:
    """Require a host tool before attempting to prepare a runtime."""
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def running_on_native_windows() -> bool:
    """Return whether the script is running on native Windows rather than WSL."""
    return os.name == "nt"


def build_jobs() -> str:
    """Return a conservative default parallelism level for local builds."""
    return str(min(os.cpu_count() or 2, 4))


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
