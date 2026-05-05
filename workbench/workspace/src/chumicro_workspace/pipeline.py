"""End-to-end pipeline that wires the loader / merger / writer modules.

``build_runtime_config`` is the convenience the deployer calls per
deploy: read workspace.yml + project config, deep-merge in precedence
order, write msgpack.  Each underlying step is also a public function
so callers that need finer control (e.g. preview a merged config
without writing) can compose them directly.

``compose_runtime_config`` is the same flow without the msgpack
write — useful for callers that need the resolved dict but not the
on-disk artifact (host-side functional-test conftests use this to
read ``[wifi]`` / ``[mqtt]`` without materialising an unused
msgpack file).

The pipeline is two gitignored layers: ``workspace.yml`` carrying
defaults + credentials in one place, plus the per-project
``config.toml``.  Both share the same section-namespaced shape;
deep-merge with project-wins precedence at any nesting depth.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.loaders import (
    read_project_config,
    read_workspace_yaml,
)
from chumicro_workspace.merge import merge_configs
from chumicro_workspace.writer import write_runtime_config


def compose_runtime_config(
    *,
    workspace_yaml: Path,
    project_config: Path | None,
) -> dict:
    """Read sources, deep-merge, return the dict.  No msgpack write.

    The host-side composition step.  Same flow ``build_runtime_config``
    runs minus the final ``write_runtime_config`` call.  Useful when
    a caller needs the resolved dict for in-memory consumption
    (e.g. networking-library functional-test conftests handing the
    merged dict to ``chumicro_pytest_device.runtime_config.set_runtime_config``)
    without leaving an unused msgpack file on disk.

    Merge precedence (lowest → highest):

    1. ``workspace.yml`` defaults (gitignored — workspace-wide
       defaults + credentials in one place)
    2. ``projects/<name>/config.{toml,yml,yaml}`` (per-project)

    Args:
        workspace_yaml: Path to ``workspace.yml`` (workspace
            defaults; only the ``defaults:`` block is consumed).
        project_config: Path to a per-project / per-library config
            file (``config.toml`` / ``.yml`` / ``.yaml``).  May be
            ``None`` (or point at a missing file) — both treated as
            "no project-level overrides", merge yields the workspace
            defaults verbatim.

    Returns:
        The fully-merged dict.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
    """
    workspace_defaults = read_workspace_yaml(workspace_yaml)
    project_data: dict = {}
    if project_config is not None and project_config.is_file():
        project_data = read_project_config(project_config)
    return merge_configs(workspace_defaults, project_data)


def build_runtime_config(
    *,
    workspace_yaml: Path,
    project_config: Path,
    output_path: Path,
) -> dict:
    """Read all sources, deep-merge, write msgpack.

    Args:
        workspace_yaml: Path to ``workspace.yml`` (workspace
            defaults; only the ``defaults:`` block is consumed).
        project_config: Path to ``projects/<name>/config.toml`` (or
            ``.yml`` / ``.yaml``).
        output_path: Where to write the msgpack file on the host.
            Typically ``projects/<name>/_generated/runtime_config.msgpack``.

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
    )
    write_runtime_config(resolved, output_path)
    return resolved
