"""Workspace health checks for ``status`` / ``doctor`` commands.

Lightweight inspections that don't talk to devices — pure local
filesystem / YAML / counting operations.  Each check returns a
:class:`HealthFinding` describing what was inspected, what state
it found, and (when relevant) a hint the user can act on.

The two consumers are :func:`chumicro_workspace.cli._cmd_status`
(prints a one-liner per check) and :func:`_cmd_doctor` (stricter,
prints remediation hints).  This module is the single source of
truth for "what looks OK / off about this workspace right now";
both commands route through the same checks so they stay
consistent.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from chumicro_deploy.config.devices_yaml import load_devices

from chumicro_workspace.loaders import (
    WorkspaceConfigError,
    read_workspace_yaml,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from pathlib import Path

    from chumicro_workspace.workspace import WorkspaceLayout


class HealthLevel(Enum):
    """Severity of a single health finding."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class HealthFinding:
    """One row in the ``status`` / ``doctor`` output.

    Attributes:
        label: Section name (``"WORKSPACE.YML"``, ``"PROJECTS"`` …).
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
    if not workspace.workspace_yaml.is_file():
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"missing at {workspace.workspace_yaml}",
            hint="run `chumicro-workspace init` to scaffold the workspace.",
        )
    try:
        read_workspace_yaml(workspace.workspace_yaml)
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
            hint="check the YAML structure against `_workspace_template/devices.yml`.",
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


def check_workspace_local_yaml(workspace: WorkspaceLayout) -> HealthFinding:
    """Validate ``workspace.local.yml`` parses as the overlay shape.

    Decision 0057: the gitignored overlay carries credentials and
    per-developer overrides as a structural deep-merge layer over
    ``workspace.yml``.  Empty / absent is fine — projects simply
    inherit committed defaults.  Malformed YAML or a non-mapping
    ``defaults:`` block earns an ERROR.
    """
    if not workspace.workspace_local_yaml.is_file():
        return HealthFinding(
            label="WORKSPACE.LOCAL.YML",
            level=HealthLevel.OK,
            message="not present (no local overrides)",
        )
    try:
        defaults = read_workspace_yaml(workspace.workspace_local_yaml)
    except WorkspaceConfigError as exception:
        return HealthFinding(
            label="WORKSPACE.LOCAL.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint=(
                "expected a top-level mapping with optional `defaults:` "
                "block matching workspace.yml's shape."
            ),
        )
    if not defaults:
        return HealthFinding(
            label="WORKSPACE.LOCAL.YML",
            level=HealthLevel.OK,
            message="present, no overrides set",
        )
    section_count = len(defaults)
    plural = "" if section_count == 1 else "s"
    return HealthFinding(
        label="WORKSPACE.LOCAL.YML",
        level=HealthLevel.OK,
        message=f"{section_count} section{plural} overriding workspace defaults",
    )


def count_projects(workspace: WorkspaceLayout) -> HealthFinding:
    """Summarize the projects tree (count + first few names)."""
    projects = workspace.list_projects()
    count = len(projects)
    if count == 0:
        return HealthFinding(
            label="PROJECTS",
            level=HealthLevel.WARN,
            message="no projects in this workspace",
            hint=(
                "run `chumicro-workspace new <name>` to scaffold one "
                "from projects/_template/."
            ),
        )
    preview_limit = 3
    preview = ", ".join(projects[:preview_limit])
    if count > preview_limit:
        preview = preview + f", … ({count - preview_limit} more)"
    plural = "" if count == 1 else "s"
    return HealthFinding(
        label="PROJECTS",
        level=HealthLevel.OK,
        message=f"{count} project{plural}: {preview}",
    )


def collect_health_findings(
    workspace: WorkspaceLayout,
) -> list[HealthFinding]:
    """Run every status check and return the findings in display order."""
    return [
        check_workspace_yaml(workspace),
        check_devices_yaml(workspace),
        check_workspace_local_yaml(workspace),
        count_projects(workspace),
    ]


# ---------------------------------------------------------------------------
# Doctor checks (Phase 2b) — stricter than status, AST + config-merge
# ---------------------------------------------------------------------------


#: Minimum Python version the workspace's pyproject.toml + deps
#: target.  Older versions surface as deps-import failures during
#: ``setup``; doctor catches it earlier.
_MIN_PYTHON_VERSION: tuple[int, int] = (3, 11)


def check_python_version() -> HealthFinding:
    """Verify the host Python is recent enough for the workspace deps."""
    major, minor = sys.version_info[:2]
    short = f"{major}.{minor}"
    full = ".".join(str(part) for part in sys.version_info[:3])
    if (major, minor) < _MIN_PYTHON_VERSION:
        required = ".".join(str(part) for part in _MIN_PYTHON_VERSION)
        return HealthFinding(
            label="PYTHON",
            level=HealthLevel.ERROR,
            message=f"got {short}, need {required}+",
            hint=(
                f"upgrade Python — the workspace's deps target "
                f"{required}+.  Your current interpreter: {sys.executable}"
            ),
        )
    return HealthFinding(
        label="PYTHON",
        level=HealthLevel.OK,
        message=full,
    )


def _project_app_path(workspace: WorkspaceLayout, project_name: str) -> Path | None:
    """Return the project's ``app.py`` path when present, else ``None``.

    Projects using the legacy ``code.py`` / ``main.py`` entry-point
    convention skip the ``run()`` check — they're not boot-shim shaped.
    """
    app_path = workspace.project_dir(project_name) / "app.py"
    return app_path if app_path.is_file() else None


def _ast_defines_top_level_run(source: str) -> bool:
    """Return True when *source* defines a top-level callable named ``run``.

    Accepts function defs (``def run(): ...``) and async function defs;
    rejects nested defs, class methods, and non-callable assignments.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == "run":
                return True
    return False


def check_project_run_functions(workspace: WorkspaceLayout) -> HealthFinding:
    """Verify each boot-shim-shaped project's ``app.py`` defines ``run()``.

    Projects without an ``app.py`` (legacy ``code.py`` / ``main.py``
    layouts) are skipped — the run() contract only binds the
    workspace-runtime boot shim.  Projects with a syntax error are
    counted as missing run() so the user sees the failure here
    rather than at deploy-time.
    """
    projects = workspace.list_projects()
    if not projects:
        return HealthFinding(
            label="PROJECT run() defs",
            level=HealthLevel.OK,
            message="no projects to check",
        )
    missing: list[str] = []
    checked = 0
    for project_name in projects:
        app_path = _project_app_path(workspace, project_name)
        if app_path is None:
            continue
        checked += 1
        if not _ast_defines_top_level_run(app_path.read_text()):
            missing.append(project_name)
    if checked == 0:
        return HealthFinding(
            label="PROJECT run() defs",
            level=HealthLevel.OK,
            message="no app.py files to check (flat-layout projects only)",
        )
    if missing:
        listed = ", ".join(missing)
        return HealthFinding(
            label="PROJECT run() defs",
            level=HealthLevel.ERROR,
            message=f"{len(missing)} of {checked} projects missing run(): {listed}",
            hint=(
                "define `def run():` in app.py — the workspace_runtime "
                "boot shim imports `projects.<name>.app` and calls run()."
            ),
        )
    return HealthFinding(
        label="PROJECT run() defs",
        level=HealthLevel.OK,
        message=f"all {checked} app.py files define run()",
    )


def collect_doctor_findings(
    workspace: WorkspaceLayout,
) -> list[HealthFinding]:
    """Run the strict (status + Python version + AST) check set."""
    return [
        check_python_version(),
        *collect_health_findings(workspace),
        check_project_run_functions(workspace),
    ]
