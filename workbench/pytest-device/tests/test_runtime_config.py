"""Tests for the runtime-config registration API and its msgpack encoding.

Two slices are covered. The ``set_runtime_config`` /
``get_runtime_config`` round-trip on a ``pytest.Config.stash`` stand-in
verifies that the value a conftest writes is the value the plugin
later reads back, including the required-keys metadata. The
``_encode_runtime_config_extra_files`` slice verifies that a ``None``
payload yields no staged file, that a registered payload yields a
single ``/runtime_config.msgpack`` entry whose bytes round-trip
through the standard decoder, and that repeated calls reuse a cached
encoding until the payload identity changes.

Hardware-side staging is out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_pytest_device import runtime_config
from chumicro_pytest_device.runtime_config import (
    get_required_keys,
    get_runtime_config,
    missing_required_keys,
    set_runtime_config,
)
from chumicro_pytest_device.session import _encode_runtime_config_extra_files
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
        """A second ``set_runtime_config`` call replaces the first one.

        A fixture that re-registers a payload after ``pytest_configure``
        must win, because the plugin reads lazily at stage time.
        """
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
        """With no ``set_runtime_config`` call made, both accessors return ``()``."""
        config = _StashConfigStub()
        assert get_required_keys(config) == ()
        assert missing_required_keys(config) == ()

    def test_iterable_input_normalized_to_tuple(self) -> None:
        """``required_keys`` accepts any iterable, and storage is a tuple."""
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
        """Missing keys come back in the order they were declared.

        Preserving declared order keeps the user-facing skip message
        readable.
        """
        config = _StashConfigStub()
        set_runtime_config(
            config,
            {"wifi.password": "p"},
            required_keys=("wifi.ssid", "wifi.password", "mqtt.broker.host"),
        )
        assert missing_required_keys(config) == ("wifi.ssid", "mqtt.broker.host")

    def test_none_payload_with_required_keys_means_all_missing(self) -> None:
        """A ``None`` payload with required keys reports every key as missing.

        This is the unconfigured-credentials path: nothing is staged,
        so every required key counts as absent.
        """
        config = _StashConfigStub()
        set_runtime_config(
            config, None, required_keys=("wifi.ssid", "wifi.password"),
        )
        assert missing_required_keys(config) == ("wifi.ssid", "wifi.password")

    def test_overwriting_resets_required_keys(self) -> None:
        """A second call without ``required_keys`` clears the previous list.

        The second registration fully replaces the first, including
        resetting required-keys back to the ``()`` default.
        """
        config = _StashConfigStub()
        set_runtime_config(
            config, {"wifi.ssid": "x"}, required_keys=("wifi.ssid",),
        )
        set_runtime_config(config, {"wifi.ssid": "x"})  # no required_keys
        assert get_required_keys(config) == ()
        assert missing_required_keys(config) == ()


class TestPerLibraryScope:
    """Two libraries' registrations must not clobber each other."""

    def test_library_scope_derived_from_conftest_path(self) -> None:
        """A functional-tests conftest path maps to its library name."""
        assert runtime_config._library_scope_from_path(
            Path("libraries/mqtt/functional_tests/conftest.py"),
        ) == "mqtt"
        assert runtime_config._library_scope_from_path(
            Path("workbench/pytest-device/tests/test_runtime_config.py"),
        ) is None

    def test_two_libraries_keep_independent_payloads_and_required_keys(
        self, monkeypatch,
    ) -> None:
        """Registering under two library scopes keeps each intact.

        Before per-scope keying the second ``set_runtime_config`` call
        overwrote the first, so one library's validation was lost or the
        other's key was demanded of it.  Scoped by library name, each
        library reads back only its own payload and required keys.
        """
        config = _StashConfigStub()
        monkeypatch.setattr(runtime_config, "_caller_library_scope", lambda: "mqtt")
        set_runtime_config(
            config,
            {"mqtt.broker.host": "h"},
            required_keys=("mqtt.broker.host",),
        )
        monkeypatch.setattr(runtime_config, "_caller_library_scope", lambda: "wifi")
        set_runtime_config(
            config,
            {"wifi.ssid": "s"},
            required_keys=("wifi.ssid", "wifi.password"),
        )

        assert get_runtime_config(config, "mqtt") == {"mqtt.broker.host": "h"}
        assert get_required_keys(config, "mqtt") == ("mqtt.broker.host",)
        assert missing_required_keys(config, "mqtt") == ()

        assert get_runtime_config(config, "wifi") == {"wifi.ssid": "s"}
        assert missing_required_keys(config, "wifi") == ("wifi.password",)

    def test_named_scope_falls_back_to_session_wide_registration(
        self, monkeypatch,
    ) -> None:
        """A library with no registration inherits a session-wide one.

        A non-library caller registers under the session-wide scope, and
        a library that never called ``set_runtime_config`` still sees it.
        """
        config = _StashConfigStub()
        monkeypatch.setattr(
            runtime_config,
            "_caller_library_scope",
            lambda: runtime_config._DEFAULT_SCOPE,
        )
        set_runtime_config(
            config, {"wifi.ssid": "s"}, required_keys=("wifi.ssid",),
        )

        assert get_required_keys(config, "unregistered-lib") == ("wifi.ssid",)
        assert missing_required_keys(config, "unregistered-lib") == ()


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
        # The encoded bytes round-trip through the standard decoder,
        # matching what the device-side loader reads back.
        decoded = unpackb(extra_files["/runtime_config.msgpack"], raw=False)
        assert decoded == payload

    def test_explicit_none_returns_none(self) -> None:
        """An explicit ``None`` registration stages no extra files.

        Conftests use this for the silent-skip path when credentials
        are missing.
        """
        config = _StashConfigStub()
        set_runtime_config(config, None)
        assert _encode_runtime_config_extra_files(config) is None

    def test_repeated_calls_reuse_cached_bytes(
        self, monkeypatch: object,
    ) -> None:
        """A steady payload encodes exactly once across many encode calls.

        Each device sweep stages the file once per file batch, so
        without caching the same dict would re-encode 50+ times per
        run.
        """
        from chumicro_pytest_device import session

        call_count = 0
        real_packb = session.packb

        def counting_packb(*args: object, **kwargs: object) -> bytes:
            nonlocal call_count
            call_count += 1
            return real_packb(*args, **kwargs)

        monkeypatch.setattr(session, "packb", counting_packb)  # type: ignore[attr-defined]
        config = _StashConfigStub()
        set_runtime_config(config, {"wifi.ssid": "Net"})

        for _ in range(5):
            _encode_runtime_config_extra_files(config)

        assert call_count == 1

    def test_overwriting_payload_invalidates_cache(
        self, monkeypatch: object,
    ) -> None:
        """Re-registering a different dict triggers a fresh encode.

        The cache keys on payload identity, so a new dict object
        forces ``packb`` to run again.
        """
        from chumicro_pytest_device import session

        call_count = 0
        real_packb = session.packb

        def counting_packb(*args: object, **kwargs: object) -> bytes:
            nonlocal call_count
            call_count += 1
            return real_packb(*args, **kwargs)

        monkeypatch.setattr(session, "packb", counting_packb)  # type: ignore[attr-defined]
        config = _StashConfigStub()

        set_runtime_config(config, {"wifi.ssid": "first"})
        _encode_runtime_config_extra_files(config)
        set_runtime_config(config, {"wifi.ssid": "second"})
        result = _encode_runtime_config_extra_files(config)

        assert call_count == 2
        assert result is not None
        decoded = unpackb(result["/runtime_config.msgpack"], raw=False)
        assert decoded == {"wifi.ssid": "second"}
