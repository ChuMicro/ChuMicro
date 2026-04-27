"""Tests for workspace health checks (Phase 2a — `status` command)."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.health import (
    SECRET_PLACEHOLDER,
    HealthLevel,
    check_devices_yaml,
    check_secrets_yaml,
    check_workspace_yaml,
    collect_health_findings,
    count_things,
)
from chumicro_workspace.workspace import WorkspaceLayout


def _layout(tmp_path: Path) -> WorkspaceLayout:
    """Drop a workspace.yml and return the layout."""
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    return WorkspaceLayout(root=tmp_path)


def _seed_thing(workspace: WorkspaceLayout, *segments: str) -> Path:
    """Create a leaf thing with an ``app.py`` entry-point."""
    target = workspace.things_dir.joinpath(*segments)
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
# count_things
# ---------------------------------------------------------------------------


class TestCountThings:
    def test_warns_when_empty(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        finding = count_things(workspace)
        assert finding.level is HealthLevel.WARN
        assert "no things" in finding.message

    def test_lists_each_when_few(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_thing(workspace, "alpha")
        _seed_thing(workspace, "beta")
        finding = count_things(workspace)
        assert finding.level is HealthLevel.OK
        assert "2 things" in finding.message
        assert "alpha" in finding.message
        assert "beta" in finding.message

    def test_truncates_when_many(self, tmp_path: Path) -> None:
        """Only the first three names render; remainder summarized."""
        workspace = _layout(tmp_path)
        for index in range(5):
            _seed_thing(workspace, f"thing_{index}")
        finding = count_things(workspace)
        assert "5 things" in finding.message
        assert "2 more" in finding.message

    def test_singular_when_one(self, tmp_path: Path) -> None:
        workspace = _layout(tmp_path)
        _seed_thing(workspace, "lonely")
        finding = count_things(workspace)
        assert finding.message.startswith("1 thing:")


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
            "THINGS",
        ]
