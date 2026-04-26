"""Tests for ``!secret <name>`` reference resolution."""

import pytest
from chumicro_workspace import UnresolvedSecretError, resolve_secrets


class TestResolveSecretsScalars:
    """Scalar values pass through; ``!secret`` strings get replaced."""

    def test_string_without_marker_passes_through(self) -> None:
        assert resolve_secrets("HomeNet", {}) == "HomeNet"

    def test_secret_marker_replaced_with_value(self) -> None:
        result = resolve_secrets("!secret wifi_password", {"wifi_password": "shh"})
        assert result == "shh"

    def test_secret_marker_strips_whitespace_around_name(self) -> None:
        result = resolve_secrets("!secret   wifi_password  ", {"wifi_password": "shh"})
        assert result == "shh"

    def test_int_passes_through(self) -> None:
        assert resolve_secrets(42, {}) == 42

    def test_none_passes_through(self) -> None:
        assert resolve_secrets(None, {}) is None

    def test_bool_passes_through(self) -> None:
        assert resolve_secrets(True, {}) is True

    def test_float_passes_through(self) -> None:
        assert resolve_secrets(3.5, {}) == 3.5

    def test_unresolved_secret_raises(self) -> None:
        with pytest.raises(UnresolvedSecretError):
            resolve_secrets("!secret missing_name", {})

    def test_unresolved_secret_subclasses_keyerror(self) -> None:
        """``except KeyError`` catches it for callers that prefer the standard exception."""
        with pytest.raises(KeyError):
            resolve_secrets("!secret missing_name", {})

    def test_resolved_value_can_be_non_string(self) -> None:
        """A secret value can be any type — int, bool, dict, etc."""
        assert resolve_secrets("!secret port", {"port": 1883}) == 1883


class TestResolveSecretsContainers:
    """Dict / list / tuple containers walk recursively."""

    def test_dict_replacement(self) -> None:
        merged = {
            "wifi": {"ssid": "HomeNet", "password": "!secret wifi_password"},
            "mqtt": {"broker": "mqtt.local"},
        }
        result = resolve_secrets(merged, {"wifi_password": "shh"})
        assert result["wifi"]["password"] == "shh"
        assert result["wifi"]["ssid"] == "HomeNet"
        assert result["mqtt"]["broker"] == "mqtt.local"

    def test_nested_dict_replacement(self) -> None:
        merged = {"app": {"feature_flags": {"token": "!secret app_token"}}}
        result = resolve_secrets(merged, {"app_token": "abc"})
        assert result["app"]["feature_flags"]["token"] == "abc"

    def test_list_replacement(self) -> None:
        merged = ["!secret name1", "literal", "!secret name2"]
        result = resolve_secrets(merged, {"name1": "a", "name2": "b"})
        assert result == ["a", "literal", "b"]

    def test_tuple_replacement_returns_tuple(self) -> None:
        merged = ("!secret name1", "literal")
        result = resolve_secrets(merged, {"name1": "a"})
        assert result == ("a", "literal")
        assert isinstance(result, tuple)

    def test_does_not_mutate_input(self) -> None:
        """Resolution returns a new structure; original is untouched."""
        original = {"wifi": {"password": "!secret wifi_password"}}
        snapshot = {"wifi": {"password": "!secret wifi_password"}}
        resolve_secrets(original, {"wifi_password": "shh"})
        assert original == snapshot
