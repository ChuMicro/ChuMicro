"""Tests for workspace health checks (Phase 2a — `status` command)."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.health import (
    SECRET_PLACEHOLDER,
    HealthLevel,
    check_devices_yaml,
    check_project_run_functions,
    check_python_version,
    check_secret_references,
    check_secrets_yaml,
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
# check_secrets_yaml
# ---------------------------------------------------------------------------


class TestCheckSecretsYaml:
    def test_warns_when_absent(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_secrets_yaml(workspace)
        assert finding.level is HealthLevel.WARN
        assert "not present" in finding.message

    def test_ok_when_empty(self, tmp_path: Path) -> None:
        """A materialized-but-uncommented secrets.yml parses to empty."""
        workspace = _layout(tmp_path)
        workspace.secrets_yaml.write_text("# all entries commented out\n")
        finding = check_secrets_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "empty" in finding.message

    def test_ok_with_real_values(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.secrets_yaml.write_text(
            "wifi_password: actual-password\nmqtt_token: tok\n",
        )
        finding = check_secrets_yaml(workspace)
        assert finding.level is HealthLevel.OK
        assert "2 keys set" in finding.message

    def test_warns_on_placeholder_value(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.secrets_yaml.write_text(
            f"wifi_password: {SECRET_PLACEHOLDER}\n"
            "api_token: real-token\n",
        )
        finding = check_secrets_yaml(workspace)
        assert finding.level is HealthLevel.WARN
        assert "wifi_password" in finding.message
        assert "api_token" not in finding.message
        assert finding.hint is not None
        assert SECRET_PLACEHOLDER in finding.hint

    def test_warns_with_multiple_placeholders_sorted(
        self, tmp_path: Path,
    ) -> None:
        """Placeholder names appear sorted so output is deterministic."""
        workspace = _layout(tmp_path)
        workspace.secrets_yaml.write_text(
            f"wifi_password: {SECRET_PLACEHOLDER}\n"
            f"api_token: {SECRET_PLACEHOLDER}\n"
            f"mqtt_token: {SECRET_PLACEHOLDER}\n",
        )
        finding = check_secrets_yaml(workspace)
        assert finding.level is HealthLevel.WARN
        # alphabetical
        listed_index = {
            name: finding.message.index(name)
            for name in ("api_token", "mqtt_token", "wifi_password")
        }
        assert (
            listed_index["api_token"]
            < listed_index["mqtt_token"]
            < listed_index["wifi_password"]
        )


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
            "SECRETS.YML",
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


def _write_secrets(workspace: WorkspaceLayout, body: str) -> None:
    workspace.secrets_yaml.write_text(body)


class TestCheckSecretReferences:
    def test_no_projects_returns_ok(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_secret_references(workspace)
        assert finding.level is HealthLevel.OK
        assert "no projects" in finding.message

    def test_all_resolve(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _write_secrets(workspace, "wifi_password: real-pw\n")
        project_dir = workspace.project_dir("alpha")
        project_dir.mkdir(parents=True)
        (project_dir / "config.toml").write_text(
            "[wifi]\nssid = 'home'\npassword = '!secret wifi_password'\n",
        )
        (project_dir / "app.py").write_text("def run(): pass\n")
        finding = check_secret_references(workspace)
        assert finding.level is HealthLevel.OK

    def test_unresolved_secret_flagged(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _write_secrets(workspace, "wifi_password: real-pw\n")
        project_dir = workspace.project_dir("alpha")
        project_dir.mkdir(parents=True)
        (project_dir / "config.toml").write_text(
            "[mqtt]\ntoken = '!secret mqtt_token'\n",
        )
        (project_dir / "app.py").write_text("def run(): pass\n")
        finding = check_secret_references(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "1 project(s)" in finding.message
        assert finding.hint is not None
        assert "alpha" in finding.hint
        assert "mqtt_token" in finding.hint

    def test_project_without_config_skipped(self, tmp_path: Path) -> None:
        """A project dir with only app.py (no config) has no secrets to check."""
        workspace = _layout(tmp_path)
        project_dir = workspace.project_dir("alpha")
        project_dir.mkdir(parents=True)
        (project_dir / "app.py").write_text("def run(): pass\n")
        finding = check_secret_references(workspace)
        assert finding.level is HealthLevel.OK


class TestCollectDoctorFindings:
    def test_runs_all_seven_checks_in_order(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        findings = collect_doctor_findings(workspace)
        labels = [finding.label for finding in findings]
        # status's four checks are bracketed by python (front) +
        # project-run + secret-refs (back).
        assert labels == [
            "PYTHON",
            "WORKSPACE.YML",
            "DEVICES.YML",
            "SECRETS.YML",
            "PROJECTS",
            "PROJECT run() defs",
            "SECRET refs",
        ]
