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
    get_runtime_config,
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
        payload = {"wifi": {"ssid": "Net", "password": "pw"}}
        set_runtime_config(config, payload)
        assert get_runtime_config(config) == payload

    def test_default_is_none(self) -> None:
        config = _StashConfigStub()
        assert get_runtime_config(config) is None

    def test_overwrites_previous_payload(self) -> None:
        """Late-binding: a fixture overwriting an earlier ``pytest_configure``
        registration must win.  The plugin reads lazily at stage time."""
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi": {"ssid": "first"}})
        set_runtime_config(config, {"wifi": {"ssid": "second"}})
        result = get_runtime_config(config)
        assert result is not None
        assert result["wifi"]["ssid"] == "second"

    def test_explicit_none_clears_payload(self) -> None:
        """Passing ``None`` explicitly suppresses staging on the next stage call."""
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi": {"ssid": "x"}})
        set_runtime_config(config, None)
        assert get_runtime_config(config) is None


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
