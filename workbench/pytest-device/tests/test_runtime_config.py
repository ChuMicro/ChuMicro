"""Tests for ``set_runtime_config`` + the plugin's ``extra_files`` wiring.

Two slices:

1. ``set_runtime_config`` / ``get_runtime_config`` round-trip on a
   ``pytest.Config.stash`` stand-in.  Confirms the conftest-side API
   contract — the value the conftest passes is the value the plugin
   later reads back.
2. The plugin's ``_encode_runtime_config_extra_files`` helper —
   ``None`` payload → ``None`` extra_files (no staging); a registered
   payload → a one-entry dict at the canonical
   ``/runtime_config.msgpack`` path with a msgpack-encoded body that
   round-trips through the standard decoder.

Hardware-side wiring (``transport.stage(extra_files=...)`` carrying
the encoded bytes onto a real CP / MP board) is out of scope here —
covered by ``test_extra_files_staging.py`` in
``workbench/deploy/tests`` for the transport contract, and by the
networking-library functional tests for end-to-end hardware
validation.
"""

from __future__ import annotations

from chumicro_pytest_device.plugin import _encode_runtime_config_extra_files
from chumicro_pytest_device.runtime_config import (
    get_required_keys,
    get_runtime_config,
    missing_required_keys,
    set_runtime_config,
)
from msgpack import unpackb


class _StashConfigStub:
    """Minimal stand-in that exposes ``Config.stash`` semantics."""

    def __init__(self) -> None:
        self.stash: dict = {}


class TestSetRuntimeConfig:
    def test_round_trips_dict(self) -> None:
        config = _StashConfigStub()
        payload = {"wifi.ssid": "Net", "wifi.password": "pw"}
        set_runtime_config(config, payload)
        assert get_runtime_config(config) == payload

    def test_default_is_none(self) -> None:
        config = _StashConfigStub()
        assert get_runtime_config(config) is None

    def test_overwrites_previous_payload(self) -> None:
        """Late-binding: a fixture overwriting an earlier ``pytest_configure``
        registration must win.  The plugin reads lazily at stage time."""
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi.ssid": "first"})
        set_runtime_config(config, {"wifi.ssid": "second"})
        result = get_runtime_config(config)
        assert result is not None
        assert result["wifi.ssid"] == "second"

    def test_explicit_none_clears_payload(self) -> None:
        """Passing ``None`` explicitly suppresses staging on the next stage call."""
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi.ssid": "x"})
        set_runtime_config(config, None)
        assert get_runtime_config(config) is None


class TestRequiredKeys:
    def test_default_is_empty_tuple(self) -> None:
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi.ssid": "x"})
        assert get_required_keys(config) == ()
        assert missing_required_keys(config) == ()

    def test_unset_returns_empty_tuple(self) -> None:
        """No ``set_runtime_config`` call ever made — neither payload
        nor required-keys are stashed."""
        config = _StashConfigStub()
        assert get_required_keys(config) == ()
        assert missing_required_keys(config) == ()

    def test_iterable_input_normalized_to_tuple(self) -> None:
        """``required_keys`` accepts any iterable; storage is a tuple."""
        config = _StashConfigStub()
        set_runtime_config(
            config,
            {"wifi.ssid": "x", "wifi.password": "p"},
            required_keys=["wifi.ssid", "wifi.password"],
        )
        assert get_required_keys(config) == ("wifi.ssid", "wifi.password")

    def test_complete_payload_has_no_missing_keys(self) -> None:
        config = _StashConfigStub()
        set_runtime_config(
            config,
            {"wifi.ssid": "x", "wifi.password": "p", "extra.key": "ok"},
            required_keys=("wifi.ssid", "wifi.password"),
        )
        assert missing_required_keys(config) == ()

    def test_partial_payload_returns_missing_subset_in_order(self) -> None:
        """Declared order is preserved so the user-facing skip message
        reads naturally."""
        config = _StashConfigStub()
        set_runtime_config(
            config,
            {"wifi.password": "p"},
            required_keys=("wifi.ssid", "wifi.password", "mqtt.broker.host"),
        )
        assert missing_required_keys(config) == ("wifi.ssid", "mqtt.broker.host")

    def test_none_payload_with_required_keys_means_all_missing(self) -> None:
        """Unconfigured-creds path: ``payload=None`` plus required keys
        means every key is "missing" because nothing's staged."""
        config = _StashConfigStub()
        set_runtime_config(
            config, None, required_keys=("wifi.ssid", "wifi.password"),
        )
        assert missing_required_keys(config) == ("wifi.ssid", "wifi.password")

    def test_overwriting_resets_required_keys(self) -> None:
        """Two ``set_runtime_config`` calls — second wins, including
        clearing required-keys back to the default ``()``."""
        config = _StashConfigStub()
        set_runtime_config(
            config, {"wifi.ssid": "x"}, required_keys=("wifi.ssid",),
        )
        set_runtime_config(config, {"wifi.ssid": "x"})  # no required_keys
        assert get_required_keys(config) == ()
        assert missing_required_keys(config) == ()


class TestEncodeRuntimeConfigExtraFiles:
    def test_no_payload_returns_none(self) -> None:
        config = _StashConfigStub()
        assert _encode_runtime_config_extra_files(config) is None

    def test_payload_encodes_to_canonical_device_path(self) -> None:
        config = _StashConfigStub()
        payload = {
            "wifi": {"ssid": "Net", "password": "pw"},
            "mqtt": {"broker": {"host": "10.0.0.5", "port": 1883}},
        }
        set_runtime_config(config, payload)
        extra_files = _encode_runtime_config_extra_files(config)
        assert extra_files is not None
        assert list(extra_files.keys()) == ["/runtime_config.msgpack"]
        # The bytes round-trip through the standard decoder, matching
        # what ``chumicro_config.load_runtime_config()`` will read on
        # the device.
        decoded = unpackb(extra_files["/runtime_config.msgpack"], raw=False)
        assert decoded == payload

    def test_explicit_none_returns_none(self) -> None:
        """A conftest that registers ``None`` (e.g. silent-skip path on missing
        creds) gets no extra_files staged."""
        config = _StashConfigStub()
        set_runtime_config(config, None)
        assert _encode_runtime_config_extra_files(config) is None
