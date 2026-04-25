"""Tests for ``chumicro_config`` — section loader + runtime config reader.

Cross-runtime: runs on CPython pytest and (via
``test_harness.run_cross_runtime``) under MicroPython + CircuitPython
unix-ports.

The ``load_runtime_config`` tests that need pytest fixtures
(``tmp_path``, ``monkeypatch``) are CPython-only because the
lightweight cross-runtime harness doesn't ship pytest's fixture
machinery.  The non-fixture-using tests cover the section-loader
shape on every runtime; the file-IO tests need CPython's tempfile
ergonomics anyway.
"""

import sys

from chumicro_config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    load_runtime_config,
    load_section,
)
from chumicro_msgpack import packb
from chumicro_test_harness import raises

_IS_CPYTHON = sys.implementation.name == "cpython"


# A minimal target class shared across most tests — mirrors the
# shape every consumer library will use.
class _ExampleConfig:
    """Stand-in for a library's typed config dataclass."""

    def __init__(
        self,
        ssid,
        password,
        hostname=None,
        connect_timeout_ms=15_000,
    ):
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms


# ---------------------------------------------------------------------------
# load_section — required keys
# ---------------------------------------------------------------------------


def test_required_keys_extracted_into_kwargs() -> None:
    """All required keys land as keyword args to the target class."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "HomeNet", "password": "secret"},
        required=("ssid", "password"),
    )
    assert result.ssid == "HomeNet"
    assert result.password == "secret"


def test_missing_required_key_raises_missing_config_key() -> None:
    """A required key absent from the dict triggers ``MissingConfigKey``."""
    with raises(MissingConfigKey):
        load_section(
            _ExampleConfig,
            {"ssid": "HomeNet"},  # missing password
            required=("ssid", "password"),
        )


def test_missing_required_caught_via_config_error() -> None:
    """``MissingConfigKey`` subclasses the library's base ``ConfigError``.

    Single-inheritance only (MP doesn't allow multiple inheritance
    from differing-layout ``Exception`` subclasses, so we couldn't
    also subclass ``KeyError`` even if we wanted the stdlib catch).
    """
    with raises(ConfigError):
        load_section(
            _ExampleConfig,
            {"ssid": "HomeNet"},
            required=("ssid", "password"),
        )


# ---------------------------------------------------------------------------
# load_section — optional keys
# ---------------------------------------------------------------------------


def test_optional_key_present_overrides_default() -> None:
    """When the optional key is in the dict, its value wins over the default."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y", "hostname": "back-porch"},
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
    assert result.hostname == "back-porch"


def test_optional_key_absent_uses_default() -> None:
    """When the optional key isn't in the dict, the default carries through."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y"},
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
    assert result.hostname is None
    assert result.connect_timeout_ms == 15_000


def test_optional_keys_default_to_empty_mapping() -> None:
    """Omitting *optional* entirely is the same as ``optional={}``."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y"},
        required=("ssid", "password"),
    )
    # __init__ default fires for hostname since load_section passed nothing.
    assert result.hostname is None


def test_required_only_works_without_optional() -> None:
    """A library with no optional keys can omit the *optional* arg entirely."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y", "extra": "ignored"},
        required=("ssid", "password"),
    )
    assert result.ssid == "x"


# ---------------------------------------------------------------------------
# load_section — unknown keys + type-coercion policy
# ---------------------------------------------------------------------------


def test_unknown_keys_are_ignored() -> None:
    """Keys not in required/optional pass through silently (ADR 0035 §7).

    Forward-compat: a thing's config can carry keys for a future
    library without breaking deploys against today's older library.
    """
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y", "future_field": 42},
        required=("ssid", "password"),
        optional={"hostname": None},
    )
    assert result.ssid == "x"
    assert not hasattr(result, "future_field")


def test_no_type_coercion_strings_stay_strings() -> None:
    """``load_section`` doesn't coerce types — caller's __init__ is the gate."""
    result = load_section(
        _ExampleConfig,
        {"ssid": "x", "password": "y", "connect_timeout_ms": "1500"},
        required=("ssid", "password"),
        optional={"connect_timeout_ms": 15_000},
    )
    assert result.connect_timeout_ms == "1500"


# ---------------------------------------------------------------------------
# load_section — non-dict input
# ---------------------------------------------------------------------------


def test_non_dict_data_raises_invalid_config_type() -> None:
    """Section value isn't a dict ⇒ ``InvalidConfigType``."""
    with raises(InvalidConfigType):
        load_section(_ExampleConfig, "not a dict", required=("ssid",))


def test_invalid_config_type_subclasses_config_error() -> None:
    """``InvalidConfigType`` inherits ``ConfigError`` (single parent)."""
    with raises(ConfigError):
        load_section(_ExampleConfig, ["list", "not", "dict"], required=("ssid",))


def test_none_section_raises_invalid_config_type() -> None:
    """``None`` (forgotten/missing section) is treated as wrong-type."""
    with raises(InvalidConfigType):
        load_section(_ExampleConfig, None, required=("ssid",))


# ---------------------------------------------------------------------------
# load_section — composition with library from_dict pattern
# ---------------------------------------------------------------------------


def test_library_from_dict_pattern_round_trips() -> None:
    """Libraries wrap load_section in a classmethod; this is the shape.

    Not testing a real library — just confirming the pattern future
    libraries (chumicro-wifi, chumicro-mqtt) will use works end to end.
    """

    class WifiConfigShape:
        def __init__(self, ssid, password, hostname=None):
            self.ssid = ssid
            self.password = password
            self.hostname = hostname

        @classmethod
        def from_dict(cls, data):
            return load_section(
                cls,
                data,
                required=("ssid", "password"),
                optional={"hostname": None},
            )

    full = {"wifi": {"ssid": "HomeNet", "password": "secret", "hostname": "back-porch"}}
    config = WifiConfigShape.from_dict(full["wifi"])
    assert config.ssid == "HomeNet"
    assert config.hostname == "back-porch"


# ---------------------------------------------------------------------------
# load_runtime_config — file IO
# ---------------------------------------------------------------------------


def test_default_path_constant_matches_adr() -> None:
    """``DEFAULT_RUNTIME_CONFIG_PATH`` is the canonical on-device location.

    Decision 0030 §1 / 0035 §8 fix this; guard against drift.
    """
    assert DEFAULT_RUNTIME_CONFIG_PATH == "/runtime_config.msgpack"


if _IS_CPYTHON:
    # Pytest-fixture-using tests — only collected under CPython where
    # the harness supports `tmp_path` / `monkeypatch`.  The lightweight
    # cross-runtime harness on MP / CP unix-port doesn't ship these.

    def test_load_runtime_config_round_trips_a_payload(tmp_path) -> None:
        """A msgpack file written + read back yields the same section dict."""
        payload = {
            "wifi": {"ssid": "HomeNet", "password": "secret"},
            "mqtt": {"broker": "mqtt.local", "port": 1883},
            "app": {"sample_period_ms": 5000},
        }
        path = str(tmp_path / "runtime_config.msgpack")
        with open(path, "wb") as handle:
            handle.write(packb(payload))
        loaded = load_runtime_config(path)
        assert loaded == payload

    def test_load_runtime_config_missing_file_raises_oserror(tmp_path) -> None:
        """A missing file raises ``OSError`` (typically ENOENT)."""
        missing = str(tmp_path / "does-not-exist.msgpack")
        with raises(OSError):
            load_runtime_config(missing)

    def test_load_runtime_config_non_dict_payload_raises_invalid_type(tmp_path) -> None:
        """A msgpack file decoding to a non-dict trips ``InvalidConfigType``."""
        path = str(tmp_path / "bad.msgpack")
        with open(path, "wb") as handle:
            handle.write(packb([1, 2, 3]))  # decodes to list, not dict
        with raises(InvalidConfigType):
            load_runtime_config(path)

    def test_load_runtime_config_default_path_is_used_when_unspecified(
        monkeypatch, tmp_path,
    ) -> None:
        """Calling without an arg reads from ``DEFAULT_RUNTIME_CONFIG_PATH``."""
        seed_path = str(tmp_path / "seeded.msgpack")
        with open(seed_path, "wb") as handle:
            handle.write(packb({"app": {"key": "value"}}))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        loaded = load_runtime_config()
        assert loaded == {"app": {"key": "value"}}
