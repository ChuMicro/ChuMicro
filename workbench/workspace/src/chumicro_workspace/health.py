"""Workspace health checks for ``status`` / ``doctor`` commands.

Lightweight inspections that don't talk to devices — pure local
filesystem / YAML / counting operations.  Each check returns a
:class:`HealthFinding` describing what was inspected, what state
it found, and (when relevant) a hint the user can act on.

The two consumers are :func:`chumicro_workspace.cli._cmd_status`
(prints a one-liner per check) and the planned ``doctor`` command
(stricter, prints remediation hints).  This module is the single
source of truth for "what looks OK / off about this workspace
right now"; both commands route through the same checks so they
stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from chumicro_workspace.devices_yaml import load_devices
from chumicro_workspace.loaders import (
    WorkspaceConfigError,
    read_secrets_yaml,
    read_workspace_yaml,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_workspace.workspace import WorkspaceLayout

#: Sentinel string the canonical workspace template ships in
#: ``_templates/secrets.yml`` for every credential entry.  When a
#: user runs ``setup`` and the materialized ``secrets.yml`` still
#: carries this value, the deploy-time ``!secret`` resolution will
#: hand the literal ``"replace-me"`` to the device — almost
#: certainly not what the user wanted.
SECRET_PLACEHOLDER: str = "replace-me"


class HealthLevel(Enum):
    """Severity of a single health finding."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class HealthFinding:
    """One row in the ``status`` / ``doctor`` output.

    Attributes:
        label: Section name (``"WORKSPACE.YML"``, ``"THINGS"`` …).
            Rendered in column-1; uppercase by convention.
        level: Severity (OK / WARN / ERROR).  Decides the prefix
            symbol used by the renderer.
        message: One-line summary of what was found.  Optional
            detail can ride along in *hint*.
        hint: Optional remediation pointer — what the user should
            do next.  Status prints it on the line below; doctor
            renders it as a bullet under the failure.
    """

    label: str
    level: HealthLevel
    message: str
    hint: str | None = None


def check_workspace_yaml(workspace: WorkspaceLayout) -> HealthFinding:
    """Verify ``workspace.yml`` parses as the expected shape."""
    try:
        read_workspace_yaml(workspace.workspace_yaml)
    except FileNotFoundError:
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"missing at {workspace.workspace_yaml}",
            hint="run `chumicro-workspace init` to scaffold the workspace.",
        )
    except WorkspaceConfigError as exception:
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint="fix the YAML structure; expected a top-level mapping.",
        )
    return HealthFinding(
        label="WORKSPACE.YML",
        level=HealthLevel.OK,
        message="valid",
    )


def check_devices_yaml(workspace: WorkspaceLayout) -> HealthFinding:
    """Count entries in ``devices.yml`` (no reachability probe)."""
    if not workspace.devices_yaml.is_file():
        return HealthFinding(
            label="DEVICES.YML",
            level=HealthLevel.WARN,
            message="not present",
            hint=(
                "run `chumicro-workspace add-device <id> "
                "--address <port>` to register a board."
            ),
        )
    try:
        data = load_devices(workspace.devices_yaml)
    except Exception as exception:  # noqa: BLE001 — every parse failure surfaces here
        return HealthFinding(
            label="DEVICES.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint="check the YAML structure against `_templates/devices.yml`.",
        )
    devices = data.get("devices", []) or []
    count = len(devices)
    if count == 0:
        return HealthFinding(
            label="DEVICES.YML",
            level=HealthLevel.WARN,
            message="no devices registered",
            hint=(
                "run `chumicro-workspace add-device <id> "
                "--address <port>` to register a board."
            ),
        )
    plural = "" if count == 1 else "s"
    return HealthFinding(
        label="DEVICES.YML",
        level=HealthLevel.OK,
        message=f"{count} device{plural} registered",
    )


def check_secrets_yaml(workspace: WorkspaceLayout) -> HealthFinding:
    """Spot un-edited template placeholders in ``secrets.yml``.

    A freshly-materialized ``secrets.yml`` (Decision 0038 §5) ships
    every entry as ``<name>: replace-me``.  When the user
    forgets to edit a key and then deploys a thing that references
    it via ``!secret``, the runtime config carries the literal
    string ``"replace-me"`` to the device — usually surfacing as a
    failed wifi connect or auth error.  Catch it before deploy.
    """
    if not workspace.secrets_yaml.is_file():
        return HealthFinding(
            label="SECRETS.YML",
            level=HealthLevel.WARN,
            message="not present",
            hint=(
                "run `chumicro-workspace setup` to materialize it from "
                "_templates/secrets.yml."
            ),
        )
    try:
        secrets = read_secrets_yaml(workspace.secrets_yaml)
    except WorkspaceConfigError as exception:
        return HealthFinding(
            label="SECRETS.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint=(
                "expected a flat top-level mapping of name → value. "
                "Check the file against `_templates/secrets.yml`."
            ),
        )
    placeholders = sorted(
        name for name, value in secrets.items()
        if isinstance(value, str) and value == SECRET_PLACEHOLDER
    )
    if placeholders:
        listed = ", ".join(placeholders)
        return HealthFinding(
            label="SECRETS.YML",
            level=HealthLevel.WARN,
            message=f"placeholder values: {listed}",
            hint=(
                f"edit secrets.yml — replace `{SECRET_PLACEHOLDER}` "
                "with real values before deploying things that use them."
            ),
        )
    if not secrets:
        return HealthFinding(
            label="SECRETS.YML",
            level=HealthLevel.OK,
            message="empty (no credentials registered yet)",
        )
    plural = "" if len(secrets) == 1 else "s"
    return HealthFinding(
        label="SECRETS.YML",
        level=HealthLevel.OK,
        message=f"{len(secrets)} key{plural} set",
    )


def count_things(workspace: WorkspaceLayout) -> HealthFinding:
    """Summarize the things tree (count + first few names)."""
    things = workspace.list_things()
    count = len(things)
    if count == 0:
        return HealthFinding(
            label="THINGS",
            level=HealthLevel.WARN,
            message="no things in this workspace",
            hint=(
                "run `chumicro-workspace new <name>` to scaffold one "
                "from things/_template/."
            ),
        )
    preview_limit = 3
    preview = ", ".join(things[:preview_limit])
    if count > preview_limit:
        preview = preview + f", … ({count - preview_limit} more)"
    plural = "" if count == 1 else "s"
    return HealthFinding(
        label="THINGS",
        level=HealthLevel.OK,
        message=f"{count} thing{plural}: {preview}",
    )


def collect_health_findings(
    workspace: WorkspaceLayout,
) -> list[HealthFinding]:
    """Run every check and return the findings in display order."""
    return [
        check_workspace_yaml(workspace),
        check_devices_yaml(workspace),
        check_secrets_yaml(workspace),
        count_things(workspace),
    ]
