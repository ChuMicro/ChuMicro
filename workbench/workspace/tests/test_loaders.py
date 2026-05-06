"""Tests for the YAML / TOML config readers."""

from pathlib import Path

import pytest
from chumicro_workspace import (
    WorkspaceConfigError,
    read_project_config,
    read_secrets_toml,
)

# ---------------------------------------------------------------------------
# read_secrets_toml
# ---------------------------------------------------------------------------


class TestReadSecretsToml:
    def test_returns_full_nested_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.toml"
        path.write_text(
            "[wifi]\n"
            'ssid = "HomeNet"\n'
            'password = "shh"\n'
            "\n"
            "[mqtt.broker]\n"
            'host = "test.mosquitto.org"\n'
            "port = 1883\n"
        )
        result = read_secrets_toml(path)
        assert result == {
            "wifi": {"ssid": "HomeNet", "password": "shh"},
            "mqtt": {"broker": {"host": "test.mosquitto.org", "port": 1883}},
        }

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.toml"
        path.write_text("")
        assert read_secrets_toml(path) == {}

    def test_comment_only_file_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.toml"
        path.write_text("# only comments\n")
        assert read_secrets_toml(path) == {}

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """``secrets.toml`` is the load-bearing device-config file;
        missing it is a fresh-clone-before-setup signal callers want
        to surface, not silently swallow.  Callers that need to
        tolerate absence check ``path.is_file()`` themselves.
        """
        path = tmp_path / "secrets.toml"
        with pytest.raises(FileNotFoundError):
            read_secrets_toml(path)


# ---------------------------------------------------------------------------
# read_project_config
# ---------------------------------------------------------------------------


class TestReadProjectConfig:
    def test_toml_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "project_config.toml"
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

    def test_legacy_config_toml_filename_works(self, tmp_path: Path) -> None:
        """``config.toml`` parses the same — accepted as a legacy name."""
        path = tmp_path / "config.toml"
        path.write_text("[wifi]\nssid = 'HomeNet'\n")
        result = read_project_config(path)
        assert result["wifi"]["ssid"] == "HomeNet"

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
        path.write_text("- one\n: two\n")
        with pytest.raises(WorkspaceConfigError):
            read_project_config(path)

    def test_yaml_parse_error_wraps_in_workspace_config_error(
        self, tmp_path: Path,
    ) -> None:
        # Malformed YAML — ruamel raises ``YAMLError`` which the
        # loader wraps in ``WorkspaceConfigError`` so callers only
        # catch one exception type.
        path = tmp_path / "config.yml"
        path.write_text("wifi: ssid: nested colon mid-flow\n  - badly indented\n")
        with pytest.raises(WorkspaceConfigError, match="parse error"):
            read_project_config(path)

    def test_yaml_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yml"
        path.write_text("")
        assert read_project_config(path) == {}
