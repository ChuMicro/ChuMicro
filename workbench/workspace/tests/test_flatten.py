"""Tests for ``flatten_config`` — the nested-to-dotted-key compose-time pass."""

import pytest
from chumicro_workspace.flatten import flatten_config


def test_flat_input_is_returned_unchanged() -> None:
    """A dict with no nested mappings round-trips."""
    source = {"wifi.ssid": "x", "mqtt.broker.host": "y"}
    assert flatten_config(source) == source


def test_one_level_nesting_flattens_to_dotted_keys() -> None:
    """Single-level nested table becomes ``parent.child``."""
    assert flatten_config({"wifi": {"ssid": "x", "password": "y"}}) == {
        "wifi.ssid": "x",
        "wifi.password": "y",
    }


def test_multi_level_nesting_flattens_recursively() -> None:
    """Deeply nested tables become full dotted paths."""
    source = {"mqtt": {"broker": {"host": "a", "port": 1883, "auth": {"username": "u"}}}}
    assert flatten_config(source) == {
        "mqtt.broker.host": "a",
        "mqtt.broker.port": 1883,
        "mqtt.broker.auth.username": "u",
    }


def test_lists_are_taken_verbatim_not_recursed() -> None:
    """List values stay as lists; the flatten only recurses into dicts."""
    assert flatten_config({"wifi": {"channels": [1, 6, 11]}}) == {
        "wifi.channels": [1, 6, 11],
    }


def test_empty_dict_yields_empty_dict() -> None:
    """No keys in → no keys out."""
    assert flatten_config({}) == {}


def test_empty_nested_dict_emits_no_keys() -> None:
    """An inner empty dict has nothing to flatten — drop it."""
    assert flatten_config({"wifi": {}}) == {}


def test_mixed_scalar_and_nested_at_same_level() -> None:
    """A dict with both a scalar and a nested table at the top level."""
    source = {"app_name": "porch-sensor", "wifi": {"ssid": "x"}}
    assert flatten_config(source) == {
        "app_name": "porch-sensor",
        "wifi.ssid": "x",
    }


def test_does_not_mutate_input() -> None:
    """The original dict is untouched after flattening."""
    source = {"wifi": {"ssid": "x"}}
    snapshot = {"wifi": {"ssid": "x"}}
    flatten_config(source)
    assert source == snapshot


def test_non_string_key_raises_value_error() -> None:
    """Runtime-config keys must be strings to be representable as dotted paths."""
    with pytest.raises(ValueError, match="must be a string"):
        flatten_config({1: "x"})


def test_non_string_key_in_nested_dict_raises() -> None:
    """The check is recursive — non-string keys at any depth fail."""
    with pytest.raises(ValueError, match="must be a string"):
        flatten_config({"wifi": {2: "y"}})


def test_none_value_passes_through() -> None:
    """``None`` is a valid scalar value — taken verbatim."""
    assert flatten_config({"wifi": {"hostname": None}}) == {"wifi.hostname": None}


def test_boolean_value_passes_through() -> None:
    """Booleans land as booleans (msgpack roundtrips them)."""
    assert flatten_config({"wifi": {"power_save": False}}) == {
        "wifi.power_save": False,
    }
