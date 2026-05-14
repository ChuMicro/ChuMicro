"""Tests for the deep per-key merge."""

import pytest
from chumicro_workspace.merge import merge_configs


class TestMergeConfigs:
    """Cover the deep-merge semantics for runtime-config sources."""

    def test_single_source_returns_copy(self) -> None:
        source = {"wifi": {"ssid": "x"}}
        result = merge_configs(source)
        assert result == source
        assert result is not source

    def test_no_sources_raises_valueerror(self) -> None:
        with pytest.raises(ValueError):
            merge_configs()

    def test_non_dict_source_raises_typeerror(self) -> None:
        with pytest.raises(TypeError):
            merge_configs({"wifi": {"ssid": "x"}}, "not a dict")  # type: ignore[arg-type]

    def test_two_dicts_keys_in_one_only_carry_through(self) -> None:
        workspace = {"wifi": {"hostname_prefix": "chu-"}}
        project = {"mqtt": {"broker": "mqtt.local"}}
        result = merge_configs(workspace, project)
        assert result == {
            "wifi": {"hostname_prefix": "chu-"},
            "mqtt": {"broker": "mqtt.local"},
        }

    def test_overlapping_section_merges_key_by_key(self) -> None:
        """Overlap merges deep, key-level within each section."""
        workspace = {"wifi": {"hostname_prefix": "chu-", "timeout_ms": 15000}}
        project = {"wifi": {"ssid": "HomeNet", "timeout_ms": 5000}}
        result = merge_configs(workspace, project)
        assert result["wifi"] == {
            "hostname_prefix": "chu-",   # from workspace
            "ssid": "HomeNet",           # from project
            "timeout_ms": 5000,          # project overrode workspace
        }

    def test_project_wins_on_scalar_conflict(self) -> None:
        workspace = {"wifi": {"timeout_ms": 15000}}
        project = {"wifi": {"timeout_ms": 5000}}
        result = merge_configs(workspace, project)
        assert result["wifi"]["timeout_ms"] == 5000

    def test_lists_replace_wholesale(self) -> None:
        """Merge is key-level, not element-level — lists replace wholesale."""
        workspace = {"app": {"sources": ["a", "b"]}}
        project = {"app": {"sources": ["c"]}}
        result = merge_configs(workspace, project)
        assert result["app"]["sources"] == ["c"]

    def test_nested_dict_merges_recursively(self) -> None:
        workspace = {"app": {"flags": {"new_ui": True, "verbose": False}}}
        project = {"app": {"flags": {"verbose": True, "experimental": True}}}
        result = merge_configs(workspace, project)
        assert result["app"]["flags"] == {
            "new_ui": True,
            "verbose": True,
            "experimental": True,
        }

    def test_three_sources_chain_left_to_right(self) -> None:
        """A future environment-defaults / global-overrides layer would compose this way."""
        workspace = {"wifi": {"a": 1}}
        environment = {"wifi": {"b": 2}}
        project = {"wifi": {"a": 99, "c": 3}}
        result = merge_configs(workspace, environment, project)
        assert result["wifi"] == {"a": 99, "b": 2, "c": 3}

    def test_does_not_mutate_inputs(self) -> None:
        workspace = {"wifi": {"hostname_prefix": "chu-"}}
        project = {"wifi": {"ssid": "HomeNet"}}
        snapshot_workspace = {"wifi": {"hostname_prefix": "chu-"}}
        snapshot_project = {"wifi": {"ssid": "HomeNet"}}
        merge_configs(workspace, project)
        assert workspace == snapshot_workspace
        assert project == snapshot_project

    def test_dict_replaces_scalar(self) -> None:
        """When the override turns a scalar into a dict, override wins wholesale."""
        workspace = {"wifi": "legacy-string"}
        project = {"wifi": {"ssid": "HomeNet"}}
        result = merge_configs(workspace, project)
        assert result["wifi"] == {"ssid": "HomeNet"}

    def test_scalar_replaces_dict(self) -> None:
        """When the override turns a dict into a scalar, override wins wholesale."""
        workspace = {"wifi": {"ssid": "HomeNet"}}
        project = {"wifi": "disabled"}
        result = merge_configs(workspace, project)
        assert result["wifi"] == "disabled"
