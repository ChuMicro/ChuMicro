"""Tests for workspace health checks (Phase 2a — `status` command)."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.health import (
    HealthLevel,
    check_devices_yaml,
    check_project_run_functions,
    check_python_version,
    check_workspace_local_yaml,
    check_workspace_yaml,
    collect_doctor_findings,
    collect_health_findings,
    count_projects,
)
from chumicro_workspace.workspace import WorkspaceLayout


def _layout(tmp_path: Path) -> WorkspaceLayout:
    """Drop a workspace.yml and return the layout."""
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    return WorkspaceLayout(root=tmp_path)


def _seed_project(workspace: WorkspaceLayout, *segments: str) -> Path:
    """Create a leaf project with an ``app.py`` entry-point."""
    target = workspace.projects_dir.joinpath(*segments)
    target.mkdir(parents=True)
    (target / "app.py").write_text("def run(): pass\n")
    return target


# ---------------------------------------------------------------------------
# check_workspace_yaml
# ---------------------------------------------------------------------------


class TestCheckWorkspaceYaml:
    def test_ok_when_valid(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_workspace_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert finding.label == "WORKSPACE.YML"

    def test_error_when_missing(self, tmp_path: Path) -> None:
        workspace = WorkspaceLayout(root=tmp_path)
        finding = check_workspace_yaml(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "missing" in finding.message
        assert finding.hint is not None

    def test_error_when_malformed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("[not, a, mapping]\n")
        workspace = WorkspaceLayout(root=tmp_path)
        finding = check_workspace_yaml(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "malformed" in finding.message


# ---------------------------------------------------------------------------
# check_devices_yaml
# ---------------------------------------------------------------------------


class TestCheckDevicesYaml:
    def test_warns_when_absent(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_devices_yaml(workspace)
        assert finding.level is HealthLevel.WARN
        assert "not present" in finding.message
        assert "add-device" in finding.hint

    def test_warns_when_empty(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.devices_yaml.write_text("devices: []\n")
        finding = check_devices_yaml(workspace)
        assert finding.level is HealthLevel.WARN
        assert "no devices" in finding.message

    def test_ok_with_count(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.devices_yaml.write_text(
            "devices:\n"
            "  - id: alpha\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.a\n"
            "  - id: beta\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.b\n",
        )
        finding = check_devices_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "2 devices" in finding.message

    def test_singular_when_one_device(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.devices_yaml.write_text(
            "devices:\n"
            "  - id: solo\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.s\n",
        )
        finding = check_devices_yaml(workspace)
        assert finding.message == "1 device registered"


# ---------------------------------------------------------------------------
# check_workspace_local_yaml (Decision 0057)
# ---------------------------------------------------------------------------


class TestCheckWorkspaceLocalYaml:
    def test_ok_when_absent(self, tmp_path: Path) -> None:
        """Missing overlay file is fine — projects inherit committed defaults."""
        workspace = _layout(tmp_path)
        finding = check_workspace_local_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "not present" in finding.message

    def test_ok_when_empty(self, tmp_path: Path) -> None:
        """A materialized-but-uncommented workspace.local.yml parses to no overrides."""
        workspace = _layout(tmp_path)
        workspace.workspace_local_yaml.write_text(
            "# all entries commented out\n",
        )
        finding = check_workspace_local_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "no overrides" in finding.message

    def test_ok_with_overrides(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.workspace_local_yaml.write_text(
            "defaults:\n"
            "  wifi:\n"
            "    password: actual-password\n"
            "  mqtt:\n"
            "    broker:\n"
            "      auth:\n"
            "        password: another\n",
        )
        finding = check_workspace_local_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "2 sections" in finding.message

    def test_singular_when_one_section(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.workspace_local_yaml.write_text(
            "defaults:\n  wifi:\n    password: pw\n",
        )
        finding = check_workspace_local_yaml(workspace)
        assert "1 section" in finding.message
        assert "1 sections" not in finding.message

    def test_error_when_malformed(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.workspace_local_yaml.write_text("- not\n- a\n- mapping\n")
        finding = check_workspace_local_yaml(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "malformed" in finding.message
        assert finding.hint is not None


# ---------------------------------------------------------------------------
# count_projects
# ---------------------------------------------------------------------------


class TestCountProjects:
    def test_warns_when_empty(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = count_projects(workspace)
        assert finding.level is HealthLevel.WARN
        assert "no projects" in finding.message

    def test_lists_each_when_few(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project(workspace, "alpha")
        _seed_project(workspace, "beta")
        finding = count_projects(workspace)
        assert finding.level is HealthLevel.OK
        assert "2 projects" in finding.message
        assert "alpha" in finding.message
        assert "beta" in finding.message

    def test_truncates_when_many(self, tmp_path: Path) -> None:
        """Only the first three names render; remainder summarized."""
        workspace = _layout(tmp_path)
        for index in range(5):
            _seed_project(workspace, f"project_{index}")
        finding = count_projects(workspace)
        assert "5 projects" in finding.message
        assert "2 more" in finding.message

    def test_singular_when_one(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project(workspace, "lonely")
        finding = count_projects(workspace)
        assert finding.message.startswith("1 project:")


# ---------------------------------------------------------------------------
# collect_health_findings
# ---------------------------------------------------------------------------


class TestCollectHealthFindings:
    def test_runs_all_four_checks_in_order(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        findings = collect_health_findings(workspace)
        labels = [finding.label for finding in findings]
        assert labels == [
            "WORKSPACE.YML",
            "DEVICES.YML",
            "WORKSPACE.LOCAL.YML",
            "PROJECTS",
        ]


# ---------------------------------------------------------------------------
# Phase 2b doctor checks
# ---------------------------------------------------------------------------


class TestCheckPythonVersion:
    def test_current_python_passes(self) -> None:
        """Tests run on Python 3.11+ — the check should always pass here."""
        finding = check_python_version()
        assert finding.level is HealthLevel.OK
        assert finding.label == "PYTHON"


def _seed_project_with_app(
    workspace: WorkspaceLayout, name: str, app_body: str,
) -> Path:
    """Create projects/<name>/app.py with *app_body* + an empty config.toml."""
    project_dir = workspace.project_dir(name)
    project_dir.mkdir(parents=True)
    (project_dir / "config.toml").write_text("")
    (project_dir / "app.py").write_text(app_body)
    return project_dir


class TestCheckProjectRunFunctions:
    def test_no_projects_returns_ok(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.OK
        assert "no projects" in finding.message

    def test_all_projects_define_run(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project_with_app(workspace, "alpha", "def run(): pass\n")
        _seed_project_with_app(workspace, "beta", "def run(): pass\n")
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.OK
        assert "all 2 app.py files" in finding.message

    def test_async_run_def_accepted(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project_with_app(workspace, "asyncproject", "async def run(): pass\n")
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.OK

    def test_missing_run_flags_project(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project_with_app(workspace, "alpha", "def run(): pass\n")
        _seed_project_with_app(
            workspace, "broken_project", "def something_else(): pass\n",
        )
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "broken_project" in finding.message
        assert finding.hint is not None

    def test_syntax_error_counts_as_missing(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_project_with_app(workspace, "broken", "def run(:\n")
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "broken" in finding.message

    def test_legacy_projects_without_app_py_skipped(self, tmp_path: Path) -> None:
        """Projects whose entry-point is code.py / main.py aren't checked.

        The run() contract binds only the boot-shim flow.  Flat projects
        with code.py at the root never get imported as
        projects.<name>.app, so they don't need a top-level run().
        """
        workspace = _layout(tmp_path)
        project_dir = workspace.project_dir("legacy")
        project_dir.mkdir(parents=True)
        (project_dir / "code.py").write_text(
            "print('flat layout, no app.py')\n",
        )
        finding = check_project_run_functions(workspace)
        assert finding.level is HealthLevel.OK
        assert "no app.py" in finding.message


class TestCollectDoctorFindings:
    def test_runs_all_six_checks_in_order(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        findings = collect_doctor_findings(workspace)
        labels = [finding.label for finding in findings]
        # status's four checks are bracketed by python (front) +
        # project-run (back).  Decision 0057 retired the
        # check_secret_references step.
        assert labels == [
            "PYTHON",
            "WORKSPACE.YML",
            "DEVICES.YML",
            "WORKSPACE.LOCAL.YML",
            "PROJECTS",
            "PROJECT run() defs",
        ]
