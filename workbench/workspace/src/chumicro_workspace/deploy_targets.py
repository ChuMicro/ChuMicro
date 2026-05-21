"""Per-project → per-device deploy mapping.

Workspaces with multiple boards register where each project should
land in ``workspace.yml``::

    deploy_targets:
      garage/door: pi-pico-w-circuitpython-board
      garage/window: [lolin-s2-circuitpython-board]
      garage/server: [pi-pico-w-mp, lolin-s2-mp]

A bare ``deploy <project>`` without ``--device`` / ``--runtime`` /
``--all-devices`` then picks the project's first registered target,
falling back to the ``devices.yml`` defaults block when the project
isn't mapped.  ``deploy --all-projects`` walks the mapping and
deploys each project to every device it lists, in declaration order.

Host-only.  The on-device boot path knows nothing about which
host-side device the bytes arrived from.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from chumicro_workspace.loaders import WorkspaceConfigError


def read_deploy_targets(workspace_yaml: Path) -> dict[str, list[str]]:
    """Parse ``deploy_targets:`` out of *workspace_yaml*.

    Returns ``{project_slash_path: [device_id, ...]}``.  Dotted keys
    (``garage.door``) normalize to slash form.  A scalar
    string value auto-promotes to a single-element list so
    one-target projects can stay terse::

        garage/door: pi-pico-w-circuitpython-board    # bare string
        garage/door: [pi-pico-w-circuitpython-board]  # equivalent

    Returns an empty dict when the block is missing or empty.

    Args:
        workspace_yaml: Path to ``workspace.yml``.

    Returns:
        Mapping from project path to a list of device ids.

    Raises:
        WorkspaceConfigError: The top-level YAML isn't a mapping,
            ``deploy_targets`` itself isn't a mapping, a key isn't
            a string, a value is neither a string nor a list, a
            list contains a non-string entry, or a list is empty.
    """
    if not workspace_yaml.is_file():
        return {}
    with workspace_yaml.open("r", encoding="utf-8") as handle:
        loaded = YAML(typ="safe").load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: top-level must be a mapping, "
            f"got {type(loaded).__name__}",
        )
    raw = loaded.get("deploy_targets")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'deploy_targets' must be a mapping, "
            f"got {type(raw).__name__}",
        )
    result: dict[str, list[str]] = {}
    for project_name, value in raw.items():
        if not isinstance(project_name, str):
            raise WorkspaceConfigError(
                f"{workspace_yaml}: 'deploy_targets' keys must be "
                f"strings, got {type(project_name).__name__}",
            )
        if isinstance(value, str):
            device_ids = [value]
        elif isinstance(value, list):
            device_ids = []
            for entry in value:
                if not isinstance(entry, str):
                    raise WorkspaceConfigError(
                        f"{workspace_yaml}: "
                        f"'deploy_targets.{project_name}' entries must "
                        f"be strings, got {type(entry).__name__}",
                    )
                device_ids.append(entry)
            if not device_ids:
                raise WorkspaceConfigError(
                    f"{workspace_yaml}: "
                    f"'deploy_targets.{project_name}' is empty; remove "
                    f"the entry or list at least one device id.",
                )
        else:
            raise WorkspaceConfigError(
                f"{workspace_yaml}: 'deploy_targets.{project_name}' "
                f"must be a string or list of strings, got "
                f"{type(value).__name__}",
            )
        result[project_name.replace(".", "/")] = device_ids
    return result
