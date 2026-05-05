"""Host-side file readers for the runtime-config pipeline.

Three input shapes per Decision 0035 (revised by Decision 0057 — drop
``!secret`` marker, replace with structural overlay):

* ``workspace.yml`` — workspace-wide defaults (YAML).  ``defaults:``
  block holds the section-namespaced dict that flows into every
  project's merged config as the lowest-precedence layer.  Committed.
* ``workspace.local.yml`` — gitignored personal overrides (YAML).
  Same shape as ``workspace.yml``; ``defaults:`` block deep-merged
  on top so credentials and per-developer values win without landing
  in git.
* ``projects/<name>/config.toml`` (or ``.yml``) — per-project config
  (TOML default; YAML accepted opt-in).  Sections override workspace
  defaults key-by-key.  Optional sibling ``config.local.toml`` (or
  ``.yml``) overrides on top — same gitignored-overlay pattern at
  the project level.

All readers return plain dicts.  TOML uses stdlib ``tomllib``
(CPython 3.11+); YAML uses ruamel.yaml (declared as a workbench dep
in ``pyproject.toml``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError


class WorkspaceConfigError(ValueError):
    """Raised when a config file's top-level structure is malformed.

    Wraps both top-level shape failures (root must be a mapping) and
    underlying parser errors (ruamel ``YAMLError``) so callers
    (most importantly ``check_workspace_yaml`` in :mod:`health`)
    only need to catch one exception type to render a clean error.
    File-level validation only (Decision 0035 §6) — schema-level
    checks happen at the library boundary when each `from_dict`
    fires on device.
    """


def _read_yaml(path: Path) -> dict[str, Any]:
    """Parse YAML + assert dict at the top level."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = YAML(typ="safe").load(handle)
    except YAMLError as parse_error:
        raise WorkspaceConfigError(
            f"{path}: parse error — {parse_error}"
        ) from parse_error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise WorkspaceConfigError(
            f"{path}: top-level must be a mapping, got {type(loaded).__name__}"
        )
    return loaded


def _read_toml(path: Path) -> dict[str, Any]:
    """Parse TOML + assert dict at the top level."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_workspace_yaml(path: Path) -> dict[str, Any]:
    """Read a ``workspace.yml`` and return its ``defaults:`` dict.

    The full workspace.yml carries other top-level sections too
    (``library_sources:``, future ``environments:``); the runtime-
    config pipeline only consumes ``defaults:``.  Returns an empty
    dict when the file lacks a ``defaults:`` block — that's the
    "no shared defaults" case, not an error.

    Also used to read ``workspace.local.yml`` (Decision 0057) — the
    gitignored overlay shares the same shape, so the same reader
    suits.  Missing files return an empty dict (callers check
    existence themselves when they need a different signal).

    Args:
        path: Path to ``workspace.yml`` or ``workspace.local.yml``.
    """
    if not path.is_file():
        return {}
    data = _read_yaml(path)
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise WorkspaceConfigError(
            f"{path}: 'defaults' must be a mapping, got {type(defaults).__name__}"
        )
    return defaults


def read_project_config(path: Path) -> dict[str, Any]:
    """Read a project's config file — TOML by default, YAML by suffix.

    Args:
        path: Path to ``config.toml`` or ``config.yml`` /
            ``config.yaml`` (or the gitignored ``config.local.*``
            sibling).  Suffix decides the parser.

    Raises:
        WorkspaceConfigError: Unrecognized suffix or malformed top
            level.
    """
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return _read_toml(path)
    if suffix in (".yml", ".yaml"):
        return _read_yaml(path)
    raise WorkspaceConfigError(
        f"{path}: unrecognized config suffix {suffix!r} "
        "(expected .toml, .yml, or .yaml)"
    )
