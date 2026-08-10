"""Tests for workspace health checks (`status` command)."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.recovery import PortHolder
from chumicro_workspace import health as health_module
from chumicro_workspace.health import (
    HealthLevel,
    check_devices_yaml,
    check_macos_fskit_wedge,
    check_project_run_functions,
    check_python_version,
    check_serial_ports_held,
    check_workspace_yaml,
    collect_doctor_findings,
    collect_health_findings,
    count_projects,
)
from chumicro_workspace.workspace import WorkspaceLayout


def _layout(tmp_path: Path) -> WorkspaceLayout:
    """Drop a workspace.yml and return the layout."""
    (tmp_path / "workspace.yml").write_text("# machinery only\n")
    (tmp_path / "secrets.toml").write_text("")
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
        assert "must be a mapping" in finding.message

    def test_error_when_yaml_parse_fails(self, tmp_path: Path) -> None:
        # Truly malformed YAML — ruamel raises ``YAMLError``.
        (tmp_path / "workspace.yml").write_text("wifi: : :\n[broken\n")
        workspace = WorkspaceLayout(root=tmp_path)
        finding = check_workspace_yaml(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "malformed" in finding.message


# ---------------------------------------------------------------------------
# check_secrets_toml
# ---------------------------------------------------------------------------


class TestCheckSecretsToml:
    def test_warns_when_absent(self, tmp_path: Path) -> None:
        # Don't use _layout (which writes secrets.toml) — make a layout
        # where secrets.toml is absent.
        (tmp_path / "workspace.yml").write_text("# machinery\n")
        workspace = WorkspaceLayout(root=tmp_path)
        from chumicro_workspace.health import check_secrets_toml  # noqa: PLC0415
        finding = check_secrets_toml(workspace)
        assert finding.level is HealthLevel.WARN
        assert "not present" in finding.message
        assert "setup" in finding.hint

    def test_ok_when_valid(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        workspace.secrets_toml.write_text('[wifi]\nssid = "x"\n')
        from chumicro_workspace.health import check_secrets_toml  # noqa: PLC0415
        finding = check_secrets_toml(workspace)
        assert finding.level is HealthLevel.OK

    def test_error_when_malformed_toml(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        # Malformed TOML — tomllib raises ``TOMLDecodeError``.
        workspace.secrets_toml.write_text("[broken\nssid = \n")
        from chumicro_workspace.health import check_secrets_toml  # noqa: PLC0415
        finding = check_secrets_toml(workspace)
        assert finding.level is HealthLevel.ERROR
        assert "parse error" in finding.message or "malformed" in finding.message


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

    def test_hint_names_the_shim_when_run_py_exists(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        (workspace.root / "run.py").write_text("# dispatcher shim\n")
        finding = check_devices_yaml(workspace)
        assert "python3 run.py add-device" in finding.hint
        assert "chumicro-workspace" not in finding.hint

    def test_hint_names_the_cli_without_the_shim(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = check_devices_yaml(workspace)
        assert "chumicro-workspace add-device" in finding.hint

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
    def test_runs_all_checks_in_order(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        findings = collect_health_findings(workspace)
        labels = [finding.label for finding in findings]
        assert labels == [
            "WORKSPACE.YML",
            "SECRETS.TOML",
            "DEVICES.YML",
            "PROJECTS",
        ]


# ---------------------------------------------------------------------------
# Doctor checks
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
    """Create projects/<name>/app.py with *app_body* + empty project_config.toml."""
    project_dir = workspace.project_dir(name)
    project_dir.mkdir(parents=True)
    (project_dir / "project_config.toml").write_text("")
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


class TestCheckMacosFskitWedge:
    def test_non_darwin_returns_not_applicable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        # Detector should not even be polled on non-darwin — guard
        # against accidental subprocess.run calls during the static
        # check on Linux / Windows CI.
        polled = []

        def fake_detect() -> bool:
            polled.append(True)
            return False

        monkeypatch.setattr(health_module, "detect_fskit_wedge", fake_detect)
        finding = check_macos_fskit_wedge()
        assert finding.level is HealthLevel.OK
        assert finding.label == "MACOS FSKIT"
        assert "not applicable" in finding.message
        assert polled == []

    def test_darwin_healthy_diskarbitrationd(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "darwin")
        monkeypatch.setattr(
            health_module, "detect_fskit_wedge", lambda: False,
        )
        finding = check_macos_fskit_wedge()
        assert finding.level is HealthLevel.OK
        assert finding.label == "MACOS FSKIT"
        assert "healthy" in finding.message

    def test_darwin_wedged_surfaces_remediation_hint(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "darwin")
        monkeypatch.setattr(
            health_module, "detect_fskit_wedge", lambda: True,
        )
        finding = check_macos_fskit_wedge()
        assert finding.level is HealthLevel.ERROR
        assert finding.label == "MACOS FSKIT"
        assert "wedged" in finding.message
        assert finding.hint is not None
        # Hint must point at both the wrapper and the doc fallback.
        assert "doctor --fix-fskit-wedge" in finding.hint
        assert "docs/troubleshooting/macos-circuitpy.md" in finding.hint


class TestCheckSerialPortsHeld:
    """Coverage for the doctor's port-holder probe."""

    def _seed_devices_yaml(self, tmp_path: Path, *device_ids: str) -> None:
        body = "devices:\n"
        for index, device_id in enumerate(device_ids):
            body += (
                f"  - id: {device_id}\n"
                f"    description: test\n"
                f"    runtime: circuitpython\n"
                f"    connection_type: serial\n"
                f"    address: /dev/cu.test{index}\n"
            )
        (tmp_path / "devices.yml").write_text(body)

    def test_windows_returns_not_applicable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "win32")
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        assert finding.label == "SERIAL PORTS"
        assert finding.level is HealthLevel.OK
        assert "not applicable" in finding.message

    def test_no_devices_yml_returns_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        assert finding.level is HealthLevel.OK
        assert "no devices.yml" in finding.message

    def test_empty_registry_returns_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        (tmp_path / "devices.yml").write_text("devices: []\n")
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        assert finding.level is HealthLevel.OK
        assert "no devices registered" in finding.message

    def test_no_holders_returns_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        self._seed_devices_yaml(tmp_path, "a", "b")
        monkeypatch.setattr(
            health_module, "diagnose_port_holders", lambda _port: [],
        )
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        assert finding.level is HealthLevel.OK
        assert "none of the 2 registered ports" in finding.message

    def test_held_port_warns_with_pid_and_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        self._seed_devices_yaml(tmp_path, "a", "b")

        def fake_diagnose(port: str):
            if port == "/dev/cu.test0":
                return [PortHolder(pid=4242, command="/bin/some-serial-app")]
            return []

        monkeypatch.setattr(
            health_module, "diagnose_port_holders", fake_diagnose,
        )
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        assert finding.level is HealthLevel.WARN
        assert "1 port(s) held" in finding.message
        assert finding.hint is not None
        assert "PID 4242" in finding.hint
        assert "/bin/some-serial-app" in finding.hint
        assert "a (/dev/cu.test0)" in finding.hint

    def test_diagnose_failure_silently_skips_that_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(health_module.sys, "platform", "linux")
        self._seed_devices_yaml(tmp_path, "a", "b")

        def fake_diagnose(port: str):
            if port == "/dev/cu.test0":
                raise RuntimeError("lsof crashed")
            return []

        monkeypatch.setattr(
            health_module, "diagnose_port_holders", fake_diagnose,
        )
        workspace = _layout(tmp_path)
        finding = check_serial_ports_held(workspace)
        # Best-effort probe — we don't fail the whole check on one
        # bad port, just skip and report the rest as clean.
        assert finding.level is HealthLevel.OK


class TestCollectDoctorFindings:
    def test_runs_all_checks_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub the detectors so the test is deterministic regardless of
        # host state — without this, a wedge on the dev machine would
        # turn the FSKit check into an ERROR and break tests that run
        # the full doctor suite.
        monkeypatch.setattr(
            health_module, "detect_fskit_wedge", lambda: False,
        )
        monkeypatch.setattr(
            health_module, "diagnose_port_holders", lambda _port: [],
        )
        workspace = _layout(tmp_path)
        findings = collect_doctor_findings(workspace)
        labels = [finding.label for finding in findings]
        # status's checks are bracketed by python (front) + project-run +
        # macOS FSKit + serial-ports (back).
        assert labels == [
            "PYTHON",
            "WORKSPACE.YML",
            "SECRETS.TOML",
            "DEVICES.YML",
            "PROJECTS",
            "PROJECT run() defs",
            "MACOS FSKIT",
            "SERIAL PORTS",
        ]
