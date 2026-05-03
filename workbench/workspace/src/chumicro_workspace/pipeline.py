"""End-to-end pipeline that wires the four loader/merger/writer modules.

``build_runtime_config`` is the convenience the deployer calls per
deploy: read workspace.yml + project config + secrets.yml, deep-merge,
resolve secrets, write msgpack.  Each underlying step is also a
public function so callers that need finer control (e.g. preview a
merged config without writing) can compose them directly.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.loaders import (
    read_project_config,
    read_secrets_yaml,
    read_workspace_yaml,
)
from chumicro_workspace.merge import merge_configs
from chumicro_workspace.secrets import resolve_secrets
from chumicro_workspace.writer import write_runtime_config


def build_runtime_config(
    *,
    workspace_yaml: Path,
    project_config: Path,
    secrets_yaml: Path,
    output_path: Path,
) -> dict:
    """Read all four sources, merge + resolve, write msgpack.

    Args:
        workspace_yaml: Path to ``workspace.yml`` (workspace
            defaults; only the ``defaults:`` block is consumed).
        project_config: Path to ``projects/<name>/config.toml`` (or
            ``.yml`` / ``.yaml``).
        secrets_yaml: Path to ``secrets.yml``.  May not exist —
            when absent, the secrets dict is empty and any
            ``!secret`` reference in the merged dict will raise
            :class:`UnresolvedSecretError`.
        output_path: Where to write the msgpack file on the host.
            Typically ``projects/<name>/_generated/runtime_config.msgpack``.

    Returns:
        The fully-merged + secrets-resolved dict that was written.
        Returning it (rather than just writing) makes the function
        easy to test + lets callers inspect / log what landed on
        device.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
        UnresolvedSecretError: A ``!secret <name>`` reference's
            name isn't in the secrets dict.
    """
    workspace_defaults = read_workspace_yaml(workspace_yaml)
    project_data = read_project_config(project_config)
    secrets = read_secrets_yaml(secrets_yaml)

    merged = merge_configs(workspace_defaults, project_data)
    resolved = resolve_secrets(merged, secrets)
    write_runtime_config(resolved, output_path)
    return resolved
