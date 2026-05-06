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
to read keys without materialising an unused msgpack file).

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
    """Read sources, deep-merge, flatten, return the flat dict.  No msgpack write.

    The host-side composition step.  Same flow ``build_runtime_config``
    runs minus the final ``write_runtime_config`` call.  Useful when
    a caller needs the resolved flat dict for in-memory consumption
    (e.g. networking-library functional-test conftests handing the
    merged dict to ``chumicro_pytest_device.runtime_config.set_runtime_config``)
    without leaving an unused msgpack file on disk.

    Merge precedence (lowest → highest):

    1. ``secrets.toml`` (workspace-wide credentials + device defaults)
    2. ``projects/<name>/project_config.toml`` (per-project)

    The deep-merged nested dict is then flattened to dotted keys
    (``{"wifi": {"ssid": "x"}}`` → ``{"wifi.ssid": "x"}``) so the
    on-device reader sees the format it consumes natively.

    Args:
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        project_config: Path to a per-project / per-library config
            file (``project_config.toml`` / ``config.toml`` /
            ``.yml`` / ``.yaml``).  May be ``None`` (or point at a
            missing file) — both treated as "no project-level
            overrides", merge yields the secrets-toml defaults
            verbatim.

    Returns:
        The fully-merged + flattened dict with dotted keys.

    Raises:
        WorkspaceConfigError: One of the YAML/TOML files has a
            malformed top level.
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
    project_config: Path,
    output_path: Path,
) -> dict:
    """Read all sources, deep-merge, flatten, write msgpack.

    Args:
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        project_config: Path to ``projects/<name>/project_config.toml``
            (or ``config.toml`` / ``.yml`` / ``.yaml``).
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
