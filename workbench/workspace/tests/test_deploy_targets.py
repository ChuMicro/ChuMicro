"""Tests for ``chumicro_workspace.deploy_targets`` (Phase 2f)."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.deploy_targets import read_deploy_targets
from chumicro_workspace.loaders import WorkspaceConfigError


class TestReadDeployTargets:
    """Parser unit tests for the ``deploy_targets:`` block."""

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert read_deploy_targets(tmp_path / "missing.yml") == {}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text("")
        assert read_deploy_targets(workspace_yaml) == {}

    def test_no_deploy_targets_block_returns_empty(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text("defaults:\n  wifi:\n    hostname_prefix: chu-\n")
        assert read_deploy_targets(workspace_yaml) == {}

    def test_string_value_promoted_to_one_element_list(
        self, tmp_path: Path,
    ) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/door: pi-pico-w-cp\n",
        )
        assert read_deploy_targets(workspace_yaml) == {
            "garage/door": ["pi-pico-w-cp"],
        }

    def test_list_value_preserved(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/server:\n"
            "    - pi-pico-w-mp\n"
            "    - lolin-s2-mp\n",
        )
        assert read_deploy_targets(workspace_yaml) == {
            "garage/server": ["pi-pico-w-mp", "lolin-s2-mp"],
        }

    def test_dotted_key_normalised_to_slash_form(self, tmp_path: Path) -> None:
        """Match the canonical slash form ``_resolve_thing_name`` returns."""
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage.door: pi-pico-w-cp\n",
        )
        assert read_deploy_targets(workspace_yaml) == {
            "garage/door": ["pi-pico-w-cp"],
        }

    def test_top_level_not_mapping_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text("- 1\n- 2\n")
        with pytest.raises(WorkspaceConfigError, match="top-level must be a mapping"):
            read_deploy_targets(workspace_yaml)

    def test_deploy_targets_not_mapping_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text("deploy_targets:\n  - bad\n")
        with pytest.raises(
            WorkspaceConfigError, match="'deploy_targets' must be a mapping",
        ):
            read_deploy_targets(workspace_yaml)

    def test_non_string_key_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        # Integer key: YAML accepts it as int, the parser must reject.
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  42: pi-pico-w-cp\n",
        )
        with pytest.raises(
            WorkspaceConfigError, match="'deploy_targets' keys must be strings",
        ):
            read_deploy_targets(workspace_yaml)

    def test_non_string_non_list_value_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/door: 42\n",
        )
        with pytest.raises(
            WorkspaceConfigError,
            match=(
                "'deploy_targets.garage/door' must be a string or list "
                "of strings"
            ),
        ):
            read_deploy_targets(workspace_yaml)

    def test_list_with_non_string_entry_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/server:\n"
            "    - pi-pico-w-mp\n"
            "    - 42\n",
        )
        with pytest.raises(
            WorkspaceConfigError,
            match="'deploy_targets.garage/server' entries must be strings",
        ):
            read_deploy_targets(workspace_yaml)

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/door: []\n",
        )
        with pytest.raises(
            WorkspaceConfigError,
            match="'deploy_targets.garage/door' is empty",
        ):
            read_deploy_targets(workspace_yaml)

    def test_multiple_things_round_trip(self, tmp_path: Path) -> None:
        """End-to-end: the documented example block parses cleanly."""
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "deploy_targets:\n"
            "  garage/door: pi-pico-w-cp\n"
            "  garage/window: [lolin-s2-cp]\n"
            "  garage/server:\n"
            "    - pi-pico-w-mp\n"
            "    - lolin-s2-mp\n",
        )
        assert read_deploy_targets(workspace_yaml) == {
            "garage/door": ["pi-pico-w-cp"],
            "garage/window": ["lolin-s2-cp"],
            "garage/server": ["pi-pico-w-mp", "lolin-s2-mp"],
        }
