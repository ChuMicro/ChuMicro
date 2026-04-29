"""Host-side file readers for the runtime-config pipeline.

Three input shapes per Decision 0035:

* ``workspace.yml`` — workspace-wide defaults (YAML).  ``defaults:``
  block holds the section-namespaced dict that flows into every
  thing's merged config as the lowest-precedence layer.
* ``things/<name>/config.toml`` (or ``.yml``) — per-thing config
  (TOML default; YAML accepted opt-in).  Sections override
  workspace defaults key-by-key.
* ``secrets.yml`` — gitignored map of secret name → value (YAML).
  Used to resolve ``!secret <name>`` references that appear in
  either of the above.

All readers return plain dicts.  TOML uses stdlib ``tomllib``
(CPython 3.11+); YAML uses PyYAML (declared as a workbench dep
in ``pyproject.toml``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


class WorkspaceConfigError(ValueError):
    """Raised when a config file's top-level structure is malformed.

    File-level validation only (Decision 0035 §6) — schema-level
    checks happen at the library boundary when each `from_dict`
    fires on device.
    """


def _read_yaml(path: Path) -> dict[str, Any]:
    """Parse YAML + assert dict at the top level."""
    with path.open("r", encoding="utf-8") as handle:
        loaded = YAML(typ="safe").load(handle)
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

    Args:
        path: Path to ``workspace.yml``.
    """
    data = _read_yaml(path)
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise WorkspaceConfigError(
            f"{path}: 'defaults' must be a mapping, got {type(defaults).__name__}"
        )
    return defaults


def read_thing_config(path: Path) -> dict[str, Any]:
    """Read a thing's config file — TOML by default, YAML by suffix.

    Args:
        path: Path to ``config.toml`` or ``config.yml`` /
            ``config.yaml``.  Suffix decides the parser.

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


def read_secrets_yaml(path: Path) -> dict[str, Any]:
    """Read a ``secrets.yml`` and return the secret-name → value dict.

    Returns an empty dict when *path* doesn't exist — the "no
    secrets configured" case.  Resolving a ``!secret <name>``
    reference against an empty secrets dict will raise
    :class:`UnresolvedSecretError` from the secrets module, which
    is the right escalation point.

    Args:
        path: Path to ``secrets.yml``.
    """
    if not path.exists():
        return {}
    return _read_yaml(path)
