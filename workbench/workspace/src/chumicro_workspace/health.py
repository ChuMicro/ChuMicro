"""Workspace health checks for the ``status`` and ``doctor`` CLI commands.

Each check runs locally (filesystem read, YAML parse, AST scan,
platform probe) and returns a :class:`HealthFinding` capturing
what was inspected, the severity, a one-line summary, and an
optional remediation hint.  No check talks to a device.

:func:`collect_health_findings` returns the small set ``status``
displays.  :func:`collect_doctor_findings` extends it with
stricter checks: Python version, project ``run()`` defs, macOS
FSKit wedge, held serial ports.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from chumicro_deploy.config.devices_yaml import load_devices
from chumicro_deploy.macos_fskit import detect_fskit_wedge
from chumicro_deploy.recovery import diagnose_port_holders

from chumicro_workspace.loaders import (
    WorkspaceConfigError,
    read_secrets_toml,
)
from chumicro_workspace.workspace import runner_invocation

if TYPE_CHECKING:  # pragma: no cover - type-only
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
        level: Severity (OK / WARN / ERROR).
        message: One-line summary of what was found.  Optional
            detail can ride along in *hint*.
        hint: Optional remediation pointer with what the user should
            do next.  Status prints it on the line below.  Doctor
            renders it as a bullet under the failure.
    """

    label: str
    level: HealthLevel
    message: str
    hint: str | None = None


def check_workspace_yaml(workspace: WorkspaceLayout) -> HealthFinding:
    """Verify ``workspace.yml`` parses as the expected shape.

    Only confirms the file exists and parses to a mapping.  Schema
    validation for the ``library_sources:`` / ``deploy_targets:`` /
    ``quality:`` blocks happens lazily inside the modules that
    consume each one.
    """
    if not workspace.workspace_yaml.is_file():
        return HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message=f"missing at {workspace.workspace_yaml}",
            hint="run `python3 run.py setup` to materialize it.",
        )
    # Import outside `try` so YAMLError is bound on the except arm.
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

    ``secrets.toml`` is gitignored and materialized on first
    ``setup``.  Its absence on a fresh clone is a setup-not-yet-run
    state rather than a configuration error.
    """
    if not workspace.secrets_toml.is_file():
        return HealthFinding(
            label="SECRETS.TOML",
            level=HealthLevel.WARN,
            message="not present",
            hint=(
                "run `chumicro-workspace setup` to materialize the "
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
    except Exception as exception:  # noqa: BLE001 - tomllib raises various
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
                f"run `{runner_invocation(workspace.root)} add-device "
                f"<id> --address <port>` to register a board."
            ),
        )
    try:
        data = load_devices(workspace.devices_yaml)
    except Exception as exception:  # noqa: BLE001 - every parse failure surfaces here
        return HealthFinding(
            label="DEVICES.YML",
            level=HealthLevel.ERROR,
            message=f"malformed: {exception}",
            hint=(
                "check the YAML structure against the shipped template "
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
                f"run `{runner_invocation(workspace.root)} add-device "
                f"<id> --address <port>` to register a board."
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
# Doctor checks
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
                f"upgrade Python; the workspace's deps target "
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

    Projects using the ``code.py`` / ``main.py`` entry-point
    convention skip the ``run()`` check.  They are not boot-shim
    shaped, so there is no ``app.py`` to AST-walk.
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

    Projects without an ``app.py`` (the ``code.py`` / ``main.py``
    layouts) are skipped.  The ``run()`` contract only binds the
    workspace-runtime boot shim.  Projects with a syntax error are
    counted as missing ``run()`` so the user sees the failure here
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
                "define `def run():` in app.py; the synthesised boot "
                "shim imports `app.run` and calls it."
            ),
        )
    return HealthFinding(
        label="PROJECT run() defs",
        level=HealthLevel.OK,
        message=f"all {checked} app.py files define run()",
    )


def check_macos_fskit_wedge() -> HealthFinding:
    """Flag the macOS FSKit wedge that makes CIRCUITPY mounts unreachable.

    On non-macOS the wedge cannot happen.  The check returns a "not
    applicable" OK row without probing.  On macOS
    :func:`detect_fskit_wedge` runs
    ``ps -o state= -p $(pgrep diskarbitrationd)`` to detect a stuck
    diskarbitrationd.  A wedged daemon surfaces as ERROR with the
    recovery command in the hint.  A healthy daemon surfaces as OK.

    Doctor-only.
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


def check_serial_ports_held(workspace: WorkspaceLayout) -> HealthFinding:
    """Flag registered devices whose serial port is held by another process.

    Walks ``devices.yml`` addresses and runs :func:`diagnose_port_holders`
    on each.  When a port has at least one holder, surfaces as a WARN
    finding listing the PIDs and commands of the holders, typically a
    serial-terminal app the user has open against the board.  A held
    port doesn't imply something is broken (the user may be debugging),
    but if the next action is a deploy, the deploy will fail with
    ``Resource busy`` until the holder is closed.

    Doctor-only.

    Returns OK on Windows (no portable lsof equivalent without
    ``handle.exe``) and when no devices are registered.
    """
    if sys.platform.startswith("win"):
        return HealthFinding(
            label="SERIAL PORTS",
            level=HealthLevel.OK,
            message="not applicable (Windows lacks portable port-holder probe)",
        )

    devices_path = workspace.root / "devices.yml"
    if not devices_path.is_file():
        return HealthFinding(
            label="SERIAL PORTS",
            level=HealthLevel.OK,
            message="no devices.yml; nothing to check",
        )

    try:
        data = load_devices(devices_path)
    except Exception:  # noqa: BLE001 - devices.yml issues surface elsewhere
        return HealthFinding(
            label="SERIAL PORTS",
            level=HealthLevel.OK,
            message="devices.yml unreadable; check skipped",
        )

    devices = data.get("devices", []) or []
    if not devices:
        return HealthFinding(
            label="SERIAL PORTS",
            level=HealthLevel.OK,
            message="no devices registered",
        )

    held_lines: list[str] = []
    for device in devices:
        port = device.get("address")
        if not port:
            continue
        try:
            holders = diagnose_port_holders(port)
        except Exception:  # noqa: BLE001 - best-effort probe
            continue
        if not holders:
            continue
        device_id = device.get("id", "<unknown>")
        for holder in holders:
            held_lines.append(
                f"{device_id} ({port}) → PID {holder.pid}: {holder.command}",
            )

    if not held_lines:
        return HealthFinding(
            label="SERIAL PORTS",
            level=HealthLevel.OK,
            message=f"none of the {len(devices)} registered ports are held",
        )

    return HealthFinding(
        label="SERIAL PORTS",
        level=HealthLevel.WARN,
        message=f"{len(held_lines)} port(s) held by another process",
        hint=(
            "Deploys will fail with `Resource busy` until the holder "
            "releases the port.  Close the serial terminal app (Mu, "
            "Thonny, screen, minicom, CoolTerm, PyCharm / VS Code "
            "serial console, an orphan mpremote) holding the port, "
            "or kill the PID directly.  Held: " + "; ".join(held_lines)
        ),
    )


def collect_doctor_findings(
    workspace: WorkspaceLayout,
) -> list[HealthFinding]:
    """Run the strict (status + Python version + AST + FSKit + ports) check set."""
    return [
        check_python_version(),
        *collect_health_findings(workspace),
        check_project_run_functions(workspace),
        check_macos_fskit_wedge(),
        check_serial_ports_held(workspace),
    ]
