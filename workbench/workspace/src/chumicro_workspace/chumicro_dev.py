"""Wires ``workspace.yml``'s ``library_sources:`` block to a sibling chumicro checkout.

When a ``chumicro-dev.toml`` file sits next to ``workspace.yml``,
the workspace runs in dev mode: chumicro libraries the project
imports come from a sibling chumicro Git checkout instead of
published packages.  This module keeps ``workspace.yml``'s
``library_sources:`` block in sync with that checkout.

* :func:`read_chumicro_dev_path` parses ``chumicro-dev.toml`` and
  resolves its ``chumicro_path`` against the workspace root.
* :func:`discover_chumicro_libraries` walks
  ``<chumicro_path>/libraries/`` and returns
  ``{import_name: src_path}`` for every library exposing a
  ``src/chumicro_<name>/__init__.py``.
* :func:`sync_library_sources` writes or replaces the managed
  ``library_sources:`` block in ``workspace.yml``.  Re-running
  ``setup`` after pulling new libraries refreshes the block
  without disturbing sibling keys or their comments.

The ``setup`` command runs all three, so a dev-mode workspace's
``library_sources`` stays current with the sibling checkout's
library set.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from chumicro_workspace.managed_block import sync_managed_block

#: Filename consulted in the workspace root.
CHUMICRO_DEV_FILENAME = "chumicro-dev.toml"

#: Comment written immediately above the managed ``library_sources:``
#: key.  The marker is descriptive only.  There is no parse-side check
#: that a user-edited block is "ours"; ``workspace.yml`` stays user-owned.
MANAGED_MARKER = (
    "managed by chumicro-workspace setup — chumicro-dev.toml mode"
)

def read_chumicro_dev_path(workspace_root: Path) -> Path | None:
    """Resolve the sibling chumicro path declared in ``chumicro-dev.toml``.

    Returns the absolute path the toml's ``chumicro_path`` value
    points at, or ``None`` when the file is missing or the key is
    unset.  Relative paths resolve against *workspace_root* (so a
    typical ``chumicro_path = "../chumicro"`` resolves to the
    expected sibling-directory layout).

    Args:
        workspace_root: Workspace root directory (where
            ``workspace.yml`` and ``chumicro-dev.toml`` live).
    """
    dev_file = workspace_root / CHUMICRO_DEV_FILENAME
    if not dev_file.is_file():
        return None
    data = tomllib.loads(dev_file.read_text(encoding="utf-8"))
    raw_path = data.get("chumicro_path")
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (workspace_root / candidate).resolve()
    return candidate


def discover_chumicro_libraries(chumicro_path: Path) -> dict[str, Path]:
    """Walk ``<chumicro_path>/libraries/`` and return ``{import_name: src_path}``.

    Each entry maps the package's importable name (``chumicro_<libname>``)
    to the directory whose children are importable under that name —
    ``<chumicro_path>/libraries/<libname>/src/``.

    Skips library directories that don't expose a recognizable src
    tree (missing ``src/chumicro_<libname>/__init__.py``) so an
    in-progress scaffold under ``libraries/`` doesn't wedge the sync.
    Hidden / dotfile dirs are skipped too.

    Returns ``{}`` when the ``libraries/`` directory itself is missing
    — caller decides whether that's a warning or an error.

    Args:
        chumicro_path: Resolved sibling chumicro repository root.
    """
    libraries_dir = chumicro_path / "libraries"
    if not libraries_dir.is_dir():
        return {}
    result: dict[str, Path] = {}
    for library_dir in sorted(libraries_dir.iterdir()):
        if not library_dir.is_dir():
            continue
        if library_dir.name.startswith("."):
            continue
        src_dir = library_dir / "src"
        if not src_dir.is_dir():
            continue
        package_dir = src_dir / f"chumicro_{library_dir.name}"
        if not package_dir.is_dir():
            continue
        if not (package_dir / "__init__.py").is_file():
            continue
        result[f"chumicro_{library_dir.name}"] = src_dir
    return result


def _relative_to_or_absolute(path: Path, anchor: Path) -> str:
    """Return *path* relative to *anchor* when possible, else absolute.

    Used to keep the written ``library_sources:`` block readable —
    a sibling chumicro checkout produces ``../chumicro/libraries/<name>/src``
    instead of a long absolute path that varies per developer.
    """
    resolved = path.resolve()
    anchor_resolved = anchor.resolve()
    try:
        return str(resolved.relative_to(anchor_resolved))
    except ValueError:
        # Path is not under anchor; use walk-up form for sibling checkouts.
        import os  # noqa: PLC0415
        return os.path.relpath(resolved, anchor_resolved)


def sync_library_sources(
    workspace_yaml: Path, libraries: dict[str, Path],
) -> bool:
    """Write or replace the managed ``library_sources:`` block in *workspace_yaml*.

    Returns ``True`` when the file was modified, ``False`` on an
    idempotent re-run.  The block REPLACES any existing top-level
    ``library_sources:`` (with or without our marker).
    Every byte outside the block is preserved; see
    :mod:`chumicro_workspace.managed_block` for why this is raw-text
    surgery rather than a ruamel round-trip.

    Paths in *libraries* are written relative to the workspace root
    when possible (sibling-checkout case produces
    ``../chumicro/libraries/<name>/src``); otherwise the absolute
    resolved path is used.  Keys are sorted alphabetically so the
    block is diff-stable across runs.

    Args:
        workspace_yaml: Path to ``workspace.yml`` (created if missing).
        libraries: ``{import_name: host_path}`` mapping — typically
            from :func:`discover_chumicro_libraries`.
    """
    workspace_dir = workspace_yaml.parent
    child_lines = [
        f"  {name}: {_relative_to_or_absolute(libraries[name], workspace_dir)}"
        for name in sorted(libraries)
    ]
    return sync_managed_block(
        workspace_yaml, "library_sources", MANAGED_MARKER, child_lines,
    )
