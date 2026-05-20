"""End-to-end pipeline that wires the loader / merger / flatten / writer modules.

``build_runtime_config`` is the convenience the deployer calls per
deploy: read ``secrets.toml`` + per-project config, deep-merge in
precedence order, **flatten to dotted keys**, write msgpack.  Each
underlying step is also a public function so callers that need finer
control (e.g. preview a merged config without writing) can compose
them directly.

``compose_runtime_config`` is the same flow without the msgpack
write — useful for callers that need the resolved flat dict but not
the on-disk artifact (host-side functional-test conftests use this
to read keys without materializing an unused msgpack file).

Both functions return the **flat** dotted-key dict — nested tables
on disk become ``"wifi.ssid"`` / ``"mqtt.broker.host"`` keys at
compose time.  See :func:`chumicro_workspace.flatten.flatten_config`.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.flatten import flatten_config
from chumicro_workspace.loaders import (
    read_project_config,
    read_secrets_toml,
)
from chumicro_workspace.merge import merge_configs
from chumicro_workspace.writer import write_runtime_config


def compose_runtime_config(
    *,
    secrets_toml: Path,
    project_config: Path | None,
) -> dict:
    """Read sources, deep-merge, flatten to dotted keys, return the dict.

    Same flow as ``build_runtime_config`` minus the
    ``write_runtime_config`` call — for callers that need the resolved
    dict in memory rather than an on-disk msgpack.  Merge precedence:
    ``secrets.toml`` defaults, overridden by the per-project config.

    Args:
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        project_config: Per-project / per-library config file.
            ``None`` or a missing path means no overrides — the
            secrets-toml defaults pass through verbatim.

    Returns:
        The merged, flattened dict with dotted keys.

    Raises:
        WorkspaceConfigError: A YAML/TOML file has a malformed top level.
    """
    secrets = read_secrets_toml(secrets_toml)
    project_data: dict = {}
    if project_config is not None and project_config.is_file():
        project_data = read_project_config(project_config)
    merged = merge_configs(secrets, project_data)
    return flatten_config(merged)


def build_runtime_config(
    *,
    secrets_toml: Path,
    project_config: Path | None,
    output_path: Path,
) -> dict:
    """Read all sources, deep-merge, flatten, write msgpack.

    Args:
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        project_config: Path to ``projects/<name>/project_config.toml``,
            or ``None`` when no per-project overrides apply.
        output_path: Where to write the msgpack file on the host.
            Typically ``projects/<name>/_generated/runtime_config.msgpack``.

    Returns:
        The fully-merged + flattened dict that was written.  Returning
        it (rather than just writing) makes the function easy to test
        + lets callers inspect / log what landed on device.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
    """
    resolved = compose_runtime_config(
        secrets_toml=secrets_toml,
        project_config=project_config,
    )
    write_runtime_config(resolved, output_path)
    return resolved
