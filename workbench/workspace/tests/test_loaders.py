"""Tests for the YAML / TOML config readers."""

from pathlib import Path

import pytest
from chumicro_workspace import (
    WorkspaceConfigError,
    read_project_config,
    read_workspace_yaml,
)

# ---------------------------------------------------------------------------
# read_workspace_yaml
# ---------------------------------------------------------------------------


class TestReadWorkspaceYaml:
    def test_returns_defaults_block(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text(
            "defaults:\n"
            "  wifi:\n"
            "    hostname_prefix: chu-\n"
            "  mqtt:\n"
            "    port: 1883\n"
        )
        result = read_workspace_yaml(path)
        assert result == {
            "wifi": {"hostname_prefix": "chu-"},
            "mqtt": {"port": 1883},
        }

    def test_missing_defaults_block_returns_empty_dict(self, tmp_path: Path) -> None:
        """No 'defaults:' section is fine — that's the no-shared-defaults case."""
        path = tmp_path / "workspace.yml"
        path.write_text("other_top_level_key: 1\n")
        assert read_workspace_yaml(path) == {}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("")
        assert read_workspace_yaml(path) == {}

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Decision 0057 reverted the silent-absent shape.

        Workspace.yml is the load-bearing config file; missing the
        primary ``workspace.yml`` is a fresh-clone-before-setup
        signal that callers want to surface, not silently swallow.
        Callers that need to tolerate absence check ``path.is_file()``
        themselves.
        """
        path = tmp_path / "workspace.yml"
        # File deliberately not created.
        with pytest.raises(FileNotFoundError):
            read_workspace_yaml(path)

    def test_top_level_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("- one\n- two\n")
        with pytest.raises(WorkspaceConfigError):
            read_workspace_yaml(path)

    def test_defaults_must_be_a_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("defaults: not-a-mapping\n")
        with pytest.raises(WorkspaceConfigError):
            read_workspace_yaml(path)


# ---------------------------------------------------------------------------
# read_project_config
# ---------------------------------------------------------------------------


class TestReadProjectConfig:
    def test_toml_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(
            "[wifi]\n"
            'ssid = "HomeNet"\n'
            "\n"
            "[app]\n"
            "sample_period_ms = 30000\n"
        )
        result = read_project_config(path)
        assert result == {
            "wifi": {"ssid": "HomeNet"},
            "app": {"sample_period_ms": 30000},
        }

    def test_yaml_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yml"
        path.write_text(
            "wifi:\n"
            "  ssid: HomeNet\n"
            "app:\n"
            "  sample_period_ms: 30000\n"
        )
        result = read_project_config(path)
        assert result["wifi"]["ssid"] == "HomeNet"
        assert result["app"]["sample_period_ms"] == 30000

    def test_yaml_extension_alias(self, tmp_path: Path) -> None:
        """``.yaml`` works the same as ``.yml``."""
        path = tmp_path / "config.yaml"
        path.write_text("wifi:\n  ssid: x\n")
        result = read_project_config(path)
        assert result["wifi"]["ssid"] == "x"

    def test_unrecognized_suffix_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text('{"wifi": {"ssid": "x"}}')
        with pytest.raises(WorkspaceConfigError):
            read_project_config(path)

    def test_yaml_top_level_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yml"
        path.write_text("- one\n- two\n")
        with pytest.raises(WorkspaceConfigError):
            read_project_config(path)
