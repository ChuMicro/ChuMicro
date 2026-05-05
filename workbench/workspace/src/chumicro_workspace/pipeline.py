"""End-to-end pipeline that wires the loader / merger / writer modules.

``build_runtime_config`` is the convenience the deployer calls per
deploy: read workspace.yml + workspace.local.yml + project config +
optional project config.local, deep-merge in precedence order, write
msgpack.  Each underlying step is also a public function so callers
that need finer control (e.g. preview a merged config without writing)
can compose them directly.

``compose_runtime_config`` is the same flow without the msgpack write
— useful for callers that need the resolved dict but not the on-disk
artifact.  Mono-repo functional-test conftests use this to read
``[wifi]`` / ``[mqtt]`` from the unified config sources without
materialising an unused msgpack file.

Decision 0057 retired the ``!secret <name>`` marker + ``secrets.yml``
in favour of a plain structural overlay (``workspace.local.yml`` /
``config.local.{toml,yml,yaml}``).  Callers no longer pass a
secrets-yaml path; gitignored-credential management is now a
deep-merge, same shape and primitive as every other config layer.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.loaders import (
    read_project_config,
    read_workspace_yaml,
)
from chumicro_workspace.merge import merge_configs
from chumicro_workspace.writer import write_runtime_config


def _project_local_path(project_config: Path) -> Path:
    """Return the ``config.local.<suffix>`` sibling of *project_config*."""
    suffix = project_config.suffix
    return project_config.with_name(project_config.stem + ".local" + suffix)


def compose_runtime_config(
    *,
    workspace_yaml: Path,
    project_config: Path | None,
    workspace_local_yaml: Path | None = None,
) -> dict:
    """Read sources, deep-merge, return the dict.  No msgpack write.

    The host-side composition step.  Same flow ``build_runtime_config``
    runs minus the final ``write_runtime_config`` call.  Useful when
    a caller needs the resolved dict for in-memory consumption
    (e.g. mono-repo functional-test conftests reading ``[wifi]`` /
    ``[mqtt]`` for the ``_test_creds.py`` shim) without leaving an
    unused msgpack file on disk.

    Merge precedence (lowest → highest):

    1. ``workspace.yml`` defaults
    2. ``workspace.local.yml`` defaults (gitignored overlay)
    3. ``projects/<name>/config.{toml,yml,yaml}``
    4. ``projects/<name>/config.local.{toml,yml,yaml}`` (gitignored
       overlay; auto-discovered as the suffix sibling of
       *project_config* — callers don't pass it explicitly)

    Args:
        workspace_yaml: Path to ``workspace.yml`` (workspace
            defaults; only the ``defaults:`` block is consumed).
        project_config: Path to a per-project / per-library config
            file (``config.toml`` / ``.yml`` / ``.yaml``).  May be
            ``None`` (or point at a missing file) — both treated as
            "no project-level overrides", merge yields the workspace
            defaults verbatim.
        workspace_local_yaml: Path to ``workspace.local.yml``.  May
            be ``None`` (treat as missing) or point at a non-existent
            file (treated as "no local overrides").  Defaults to the
            sibling of *workspace_yaml* when not explicitly passed.

    Returns:
        The fully-merged dict.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
    """
    workspace_defaults = read_workspace_yaml(workspace_yaml)
    if workspace_local_yaml is None:
        workspace_local_yaml = workspace_yaml.with_name("workspace.local.yml")
    workspace_local_defaults = read_workspace_yaml(workspace_local_yaml)

    project_data: dict = {}
    project_local_data: dict = {}
    if project_config is not None and project_config.is_file():
        project_data = read_project_config(project_config)
        project_local = _project_local_path(project_config)
        if project_local.is_file():
            project_local_data = read_project_config(project_local)

    return merge_configs(
        workspace_defaults,
        workspace_local_defaults,
        project_data,
        project_local_data,
    )


def build_runtime_config(
    *,
    workspace_yaml: Path,
    project_config: Path,
    output_path: Path,
    workspace_local_yaml: Path | None = None,
) -> dict:
    """Read all sources, deep-merge, write msgpack.

    Args:
        workspace_yaml: Path to ``workspace.yml`` (workspace
            defaults; only the ``defaults:`` block is consumed).
        project_config: Path to ``projects/<name>/config.toml`` (or
            ``.yml`` / ``.yaml``).  Auto-discovers a sibling
            ``config.local.<suffix>`` for per-project gitignored
            overrides when present.
        output_path: Where to write the msgpack file on the host.
            Typically ``projects/<name>/_generated/runtime_config.msgpack``.
        workspace_local_yaml: Path to ``workspace.local.yml``.
            Defaults to the sibling of *workspace_yaml*.  Missing
            file is fine (treated as "no overrides").

    Returns:
        The fully-merged dict that was written.  Returning it
        (rather than just writing) makes the function easy to test
        + lets callers inspect / log what landed on device.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
    """
    resolved = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
    )
    write_runtime_config(resolved, output_path)
    return resolved
