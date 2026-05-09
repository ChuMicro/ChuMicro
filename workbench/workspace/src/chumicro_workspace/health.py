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
from chumicro_deploy.macos_fskit import detect_fskit_wedge

from chumicro_workspace.loaders import (
    WorkspaceConfigError,
    read_secrets_toml,
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
    """Verify ``workspace.yml`` parses as the expected shape.

    Only confirms the file exists and parses to a mapping — schema
    validation for the ``library_sources:`` / ``deploy_targets:`` /
    ``quality:`` blocks happens lazily inside the modules that
    consume each one.
    """
    if not workspace.workspace_yaml.is_file():
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"missing at {workspace.workspace_yaml}",
            hint="run `chumicro-workspace init` to scaffold the workspace.",
        )
    # Import outside the `try` so pyright can prove `YAMLError` is bound on
    # the `except` arm — an import failure inside the try would short-circuit
    # before the binding, which pyright correctly flags.  ruamel.yaml is a
    # hard dependency; if the import fails, we want the ImportError to
    # surface, not a misleading "malformed YAML" finding.
    from ruamel.yaml import YAML, YAMLError  # noqa: PLC0415
    try:
        with workspace.workspace_yaml.open("r", encoding="utf-8") as handle:
            loaded = YAML(typ="safe").load(handle)
    except YAMLError as exception:
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint="fix the YAML structure; expected a top-level mapping.",
        )
    if loaded is not None and not isinstance(loaded, dict):
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"top-level must be a mapping, got {type(loaded).__name__}",
            hint="fix the YAML structure; expected a top-level mapping.",
        )
    return HealthFinding(
        label="WORKSPACE.YML",
        level=HealthLevel.OK,
        message="valid",
    )


def check_secrets_toml(workspace: WorkspaceLayout) -> HealthFinding:
    """Verify ``secrets.toml`` exists and parses cleanly.

    ``secrets.toml`` is gitignored and materialised on first
    ``setup`` — its absence on a fresh clone is a setup-not-yet-run
    state rather than a configuration error.
    """
    if not workspace.secrets_toml.is_file():
        return HealthFinding(
            label="SECRETS.TOML",
            level=HealthLevel.WARN,
            message="not present",
            hint=(
                "run `chumicro-workspace setup` to materialise the "
                "starter, then edit it with your wifi / broker credentials."
            ),
        )
    try:
        read_secrets_toml(workspace.secrets_toml)
    except WorkspaceConfigError as exception:
        return HealthFinding(
            label="SECRETS.TOML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint="fix the TOML structure; expected nested tables of strings.",
        )
    except Exception as exception:  # noqa: BLE001 — tomllib raises various
        return HealthFinding(
            label="SECRETS.TOML",
            level=HealthLevel.ERROR,
            message=f"parse error: {exception}",
            hint="fix the TOML structure; expected nested tables of strings.",
        )
    return HealthFinding(
        label="SECRETS.TOML",
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
            hint=(
                "check the YAML structure against the canonical template "
                "(chumicro_deploy.read_devices_yml_template())."
            ),
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
        check_secrets_toml(workspace),
        check_devices_yaml(workspace),
        count_projects(workspace),
    ]


# ---------------------------------------------------------------------------
# Doctor checks — stricter than status, AST + config-merge
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
                "define `def run():` in app.py — the synthesised boot "
                "shim imports `app.run` and calls it."
            ),
        )
    return HealthFinding(
        label="PROJECT run() defs",
        level=HealthLevel.OK,
        message=f"all {checked} app.py files define run()",
    )


def check_macos_fskit_wedge() -> HealthFinding:
    """Flag the macOS FSKit wedge that turns CIRCUITPY mounts unreachable.

    On non-macOS the wedge mode does not exist —
    :func:`detect_fskit_wedge` returns ``False`` immediately, surfacing
    here as a "not applicable" OK row that the doctor renderer keeps
    out of the way.  On macOS the detector probes
    ``ps -o state= -p $(pgrep diskarbitrationd)``; uninterruptible
    kernel wait (``Us``) is the wedge signature.

    Doctor-only — the subprocess probe is too heavy for every
    ``status`` poll, but doctor is the diagnose-deeply surface where
    catching a wedge before the user runs into a 30-second-per-deploy
    failure cascade is the whole point.
    """
    if sys.platform != "darwin":
        return HealthFinding(
            label="MACOS FSKIT",
            level=HealthLevel.OK,
            message="not applicable (macOS-only check)",
        )
    if detect_fskit_wedge():
        return HealthFinding(
            label="MACOS FSKIT",
            level=HealthLevel.ERROR,
            message="diskarbitrationd is wedged in uninterruptible wait",
            hint=(
                "CIRCUITPY drives cannot mount until the stuck "
                "daemons are killed.  Run `chumicro-workspace doctor "
                "--fix-fskit-wedge` to clear it (sudo will prompt for "
                "your password), or paste the recovery command from "
                "docs/troubleshooting/macos-circuitpy.md manually."
            ),
        )
    return HealthFinding(
        label="MACOS FSKIT",
        level=HealthLevel.OK,
        message="diskarbitrationd healthy",
    )


def collect_doctor_findings(
    workspace: WorkspaceLayout,
) -> list[HealthFinding]:
    """Run the strict (status + Python version + AST + FSKit) check set."""
    return [
        check_python_version(),
        *collect_health_findings(workspace),
        check_project_run_functions(workspace),
        check_macos_fskit_wedge(),
    ]
