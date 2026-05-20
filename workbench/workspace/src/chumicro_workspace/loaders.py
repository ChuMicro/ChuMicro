"""Host-side file readers for the runtime-config pipeline.

Two input shapes, both TOML:

* ``secrets.toml`` — workspace-wide credentials + device defaults
  (gitignored, materialized on first ``setup`` from the canonical
  template).  The whole file is the device config — no ``defaults:``
  wrapper, no other top-level blocks.  Keys are nested TOML tables
  (``[wifi] ssid = "x"``); compose-time flattening produces the wire
  shape the on-device reader consumes.
* ``projects/<name>/project_config.toml`` — per-project knobs that
  override the workspace defaults at deploy time.

``workspace.yml`` is the workspace **machinery** file (``library_sources``,
``deploy_targets``, ``quality``, ``environments``) — separate concern,
read by other modules (:mod:`chumicro_workspace.import_graph`,
:mod:`chumicro_workspace.deploy_targets`).  It never flows onto a
device; this module doesn't touch it.

Both readers return plain dicts via stdlib ``tomllib`` (CPython 3.11+).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


class WorkspaceConfigError(ValueError):
    """Raised when a config file's top-level structure is malformed.

    Wraps both top-level shape failures (root must be a mapping) and
    underlying parser errors (ruamel ``YAMLError``) so callers
    (most importantly ``check_workspace_yaml`` in :mod:`health`)
    only need to catch one exception type to render a clean error.
    File-level validation only — schema-level checks happen at the
    library boundary when each ``from_config`` fires on device.
    """


def _read_toml(path: Path) -> dict[str, Any]:
    """Parse TOML + assert dict at the top level."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_secrets_toml(path: Path) -> dict[str, Any]:
    """Read a ``secrets.toml`` and return its contents as a nested dict.

    The whole file is the device config — no ``defaults:`` wrapper.
    Returns an empty dict when the file is empty.  TOML stdlib
    guarantees the top level is a table, so no shape check is needed
    on this side — malformed bytes raise :class:`tomllib.TOMLDecodeError`.

    Args:
        path: Path to ``secrets.toml``.

    Raises:
        FileNotFoundError: When *path* does not exist.  Callers that
            want to tolerate its absence should check ``path.is_file()``
            first.
        tomllib.TOMLDecodeError: File is malformed TOML.
    """
    return _read_toml(path)


def read_project_config(path: Path) -> dict[str, Any]:
    """Read a project's ``project_config.toml``.

    Args:
        path: Path to ``project_config.toml``.

    Raises:
        FileNotFoundError: *path* does not exist.
        tomllib.TOMLDecodeError: File is malformed TOML.
    """
    return _read_toml(path)
