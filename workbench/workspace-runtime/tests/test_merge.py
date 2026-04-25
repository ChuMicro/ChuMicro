"""Tests for the deep per-key merge."""

import pytest
from chumicro_workspace_runtime import merge_configs


class TestMergeConfigs:
    """Cover the merge semantics from Decision 0035 §5."""

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
        thing = {"mqtt": {"broker": "mqtt.local"}}
        result = merge_configs(workspace, thing)
        assert result == {
            "wifi": {"hostname_prefix": "chu-"},
            "mqtt": {"broker": "mqtt.local"},
        }

    def test_overlapping_section_merges_key_by_key(self) -> None:
        """Per ADR 0035 §5: deep, key-level within sections."""
        workspace = {"wifi": {"hostname_prefix": "chu-", "timeout_ms": 15000}}
        thing = {"wifi": {"ssid": "HomeNet", "timeout_ms": 5000}}
        result = merge_configs(workspace, thing)
        assert result["wifi"] == {
            "hostname_prefix": "chu-",   # from workspace
            "ssid": "HomeNet",           # from thing
            "timeout_ms": 5000,          # thing overrode workspace
        }

    def test_thing_wins_on_scalar_conflict(self) -> None:
        workspace = {"wifi": {"timeout_ms": 15000}}
        thing = {"wifi": {"timeout_ms": 5000}}
        result = merge_configs(workspace, thing)
        assert result["wifi"]["timeout_ms"] == 5000

    def test_lists_replace_wholesale(self) -> None:
        """ADR 0035 §5: merge is key-level, not element-level."""
        workspace = {"app": {"sources": ["a", "b"]}}
        thing = {"app": {"sources": ["c"]}}
        result = merge_configs(workspace, thing)
        assert result["app"]["sources"] == ["c"]

    def test_nested_dict_merges_recursively(self) -> None:
        workspace = {"app": {"flags": {"new_ui": True, "verbose": False}}}
        thing = {"app": {"flags": {"verbose": True, "experimental": True}}}
        result = merge_configs(workspace, thing)
        assert result["app"]["flags"] == {
            "new_ui": True,
            "verbose": True,
            "experimental": True,
        }

    def test_three_sources_chain_left_to_right(self) -> None:
        """A future environment-defaults / global-overrides layer would compose this way."""
        workspace = {"wifi": {"a": 1}}
        environment = {"wifi": {"b": 2}}
        thing = {"wifi": {"a": 99, "c": 3}}
        result = merge_configs(workspace, environment, thing)
        assert result["wifi"] == {"a": 99, "b": 2, "c": 3}

    def test_does_not_mutate_inputs(self) -> None:
        workspace = {"wifi": {"hostname_prefix": "chu-"}}
        thing = {"wifi": {"ssid": "HomeNet"}}
        snapshot_workspace = {"wifi": {"hostname_prefix": "chu-"}}
        snapshot_thing = {"wifi": {"ssid": "HomeNet"}}
        merge_configs(workspace, thing)
        assert workspace == snapshot_workspace
        assert thing == snapshot_thing

    def test_dict_replaces_scalar(self) -> None:
        """When the override turns a scalar into a dict, override wins wholesale."""
        workspace = {"wifi": "legacy-string"}
        thing = {"wifi": {"ssid": "HomeNet"}}
        result = merge_configs(workspace, thing)
        assert result["wifi"] == {"ssid": "HomeNet"}

    def test_scalar_replaces_dict(self) -> None:
        """When the override turns a dict into a scalar, override wins wholesale."""
        workspace = {"wifi": {"ssid": "HomeNet"}}
        thing = {"wifi": "disabled"}
        result = merge_configs(workspace, thing)
        assert result["wifi"] == "disabled"
