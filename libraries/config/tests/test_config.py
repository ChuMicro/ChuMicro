"""Tests for ``chumicro_config``: flat-key runtime config + section loader.

Cross-runtime: runs on CPython pytest, and under MicroPython +
CircuitPython unix-ports via ``pytest libraries/config/tests --target
unix-port`` (the ``chumicro-pytest-device`` plugin's unix-port
backend).

The ``load_runtime_config`` tests that need pytest fixtures
(``tmp_path``, ``monkeypatch``) are CPython-only because the
lightweight cross-runtime harness doesn't ship pytest's fixture
machinery.  The non-fixture-using tests cover the flat-key shape on
every runtime.
"""

import sys

from chumicro_config import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    RuntimeConfig,
    load_runtime_config,
    load_section,
    try_load_section,
)
from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH
from chumicro_msgpack import packb
from chumicro_test_harness import raises

_IS_CPYTHON = sys.implementation.name == "cpython"


# A minimal target class shared across most tests. Mirrors the
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
# RuntimeConfig: flat-key dict-like wrapper
# ---------------------------------------------------------------------------


def test_runtime_config_get_returns_value_when_key_present() -> None:
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert config.get("wifi.ssid") == "HomeNet"


def test_runtime_config_get_returns_none_on_miss() -> None:
    """Standard ``.get`` semantics. Missing key returns ``None``."""
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert config.get("wifi.password") is None


def test_runtime_config_get_returns_default_when_supplied() -> None:
    """``.get(key, default)`` falls back to *default* on miss."""
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert config.get("wifi.password", "fallback") == "fallback"


def test_runtime_config_getitem_raises_missing_config_key_on_miss() -> None:
    """``config[key]`` raises ``MissingConfigKey`` (not ``KeyError``).

    Single-inheritance constraint on MicroPython rules out
    multi-parenting from ``KeyError``. See ``MissingConfigKey``
    docstring.  Catch via ``ConfigError`` for cross-runtime portability.
    """
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    with raises(MissingConfigKey):
        _ = config["wifi.password"]


def test_runtime_config_getitem_returns_value_when_present() -> None:
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert config["wifi.ssid"] == "HomeNet"


def test_runtime_config_require_returns_value_when_present() -> None:
    """``.require()`` is the named-intent version of ``[]``."""
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert config.require("wifi.ssid") == "HomeNet"


def test_runtime_config_require_raises_missing_config_key_on_miss() -> None:
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    with raises(MissingConfigKey):
        config.require("wifi.password")


def test_runtime_config_contains_checks_membership() -> None:
    config = RuntimeConfig({"wifi.ssid": "HomeNet"})
    assert "wifi.ssid" in config
    assert "wifi.password" not in config


def test_runtime_config_none_data_yields_empty() -> None:
    """``RuntimeConfig(None)`` is valid. Yields an empty config."""
    config = RuntimeConfig(None)
    assert config.get("anything") is None
    assert "anything" not in config


def test_missing_config_key_subclasses_config_error() -> None:
    config = RuntimeConfig({})
    with raises(ConfigError):
        config["missing"]


# ---------------------------------------------------------------------------
# load_section: required keys with a shared prefix
# ---------------------------------------------------------------------------


def test_load_section_required_keys_extracted_into_kwargs() -> None:
    """All required subkeys land as keyword args to the target class."""
    result = load_section(
        _ExampleConfig,
        {"wifi.ssid": "HomeNet", "wifi.password": "secret"},
        prefix="wifi",
        required=("ssid", "password"),
    )
    assert result.ssid == "HomeNet"
    assert result.password == "secret"


def test_load_section_works_against_runtime_config_wrapper() -> None:
    """Reads through ``RuntimeConfig`` too. Same code path."""
    runtime = RuntimeConfig({"wifi.ssid": "HomeNet", "wifi.password": "secret"})
    result = load_section(
        _ExampleConfig,
        runtime,
        prefix="wifi",
        required=("ssid", "password"),
    )
    assert result.ssid == "HomeNet"


def test_load_section_missing_required_key_raises_missing_config_key() -> None:
    """A required key absent from the dict triggers ``MissingConfigKey``."""
    with raises(MissingConfigKey):
        load_section(
            _ExampleConfig,
            {"wifi.ssid": "HomeNet"},
            prefix="wifi",
            required=("ssid", "password"),
        )


def test_load_section_optional_key_present_overrides_default() -> None:
    """Present optional keys win over the declared default."""
    result = load_section(
        _ExampleConfig,
        {
            "wifi.ssid": "x",
            "wifi.password": "y",
            "wifi.hostname": "back-porch",
        },
        prefix="wifi",
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
    assert result.hostname == "back-porch"


def test_load_section_optional_key_absent_uses_default() -> None:
    """Missing optional key applies the declared default."""
    result = load_section(
        _ExampleConfig,
        {"wifi.ssid": "x", "wifi.password": "y"},
        prefix="wifi",
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
    assert result.hostname is None
    assert result.connect_timeout_ms == 15_000


def test_load_section_unknown_keys_are_ignored() -> None:
    """Keys outside the prefix's declared subkeys pass through silently.

    Forward-compat: a project's flat config can carry keys for a
    future library without breaking deploys against today's older
    library.
    """
    result = load_section(
        _ExampleConfig,
        {
            "wifi.ssid": "x",
            "wifi.password": "y",
            "wifi.future_field": 42,
            "app.unrelated": "irrelevant",
        },
        prefix="wifi",
        required=("ssid", "password"),
        optional={"hostname": None},
    )
    assert result.ssid == "x"
    assert not hasattr(result, "future_field")


def test_load_section_no_type_coercion() -> None:
    """``load_section`` doesn't coerce types. The caller's ``__init__`` is the gate."""
    result = load_section(
        _ExampleConfig,
        {
            "wifi.ssid": "x",
            "wifi.password": "y",
            "wifi.connect_timeout_ms": "1500",
        },
        prefix="wifi",
        required=("ssid", "password"),
        optional={"connect_timeout_ms": 15_000},
    )
    assert result.connect_timeout_ms == "1500"


def test_load_section_none_config_raises_invalid_type() -> None:
    """``config=None`` is wrong-shape. The soft path lives in ``try_load_section``."""
    with raises(InvalidConfigType):
        load_section(
            _ExampleConfig,
            None,
            prefix="wifi",
            required=("ssid",),
        )


def test_load_section_non_dict_config_raises_invalid_type() -> None:
    """Strings, lists, scalars are not valid runtime configs."""
    with raises(InvalidConfigType):
        load_section(
            _ExampleConfig,
            "not a config",
            prefix="wifi",
            required=("ssid",),
        )


def test_load_section_invalid_type_subclasses_config_error() -> None:
    with raises(ConfigError):
        load_section(
            _ExampleConfig,
            ["list", "not", "dict"],
            prefix="wifi",
            required=("ssid",),
        )


def test_load_section_library_pattern_round_trips() -> None:
    """The shape every config-consuming library wraps: classmethod + load_section."""

    class WifiConfigShape:
        def __init__(self, ssid, password, hostname=None):
            self.ssid = ssid
            self.password = password
            self.hostname = hostname

        @classmethod
        def from_config(cls, config):
            return load_section(
                cls,
                config,
                prefix="wifi",
                required=("ssid", "password"),
                optional={"hostname": None},
            )

    config = {
        "wifi.ssid": "HomeNet",
        "wifi.password": "secret",
        "wifi.hostname": "back-porch",
    }
    built = WifiConfigShape.from_config(config)
    assert built.ssid == "HomeNet"
    assert built.hostname == "back-porch"


# ---------------------------------------------------------------------------
# try_load_section: soft-load (returns None instead of raising)
# ---------------------------------------------------------------------------


def test_try_load_section_returns_none_when_config_is_none() -> None:
    """``config=None`` short-circuits. No creds deployed."""
    result = try_load_section(
        _ExampleConfig, None,
        prefix="wifi", required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_none_when_config_not_dict_like() -> None:
    """Non-dict, non-RuntimeConfig values short-circuit."""
    result = try_load_section(
        _ExampleConfig, "scalar",
        prefix="wifi", required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_none_when_required_key_missing() -> None:
    """Missing required key returns ``None``, not ``MissingConfigKey``."""
    result = try_load_section(
        _ExampleConfig, {"wifi.ssid": "Net"},
        prefix="wifi", required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_instance_when_keys_present() -> None:
    """Returns a built instance when all required subkeys are present."""
    result = try_load_section(
        _ExampleConfig,
        {"wifi.ssid": "Net", "wifi.password": "pw"},
        prefix="wifi",
        required=("ssid", "password"),
    )
    assert result is not None
    assert result.ssid == "Net"


def test_try_load_section_applies_optional_defaults() -> None:
    """Optional subkeys that are absent receive their declared defaults."""
    result = try_load_section(
        _ExampleConfig,
        {"wifi.ssid": "Net", "wifi.password": "pw"},
        prefix="wifi",
        required=("ssid", "password"),
        optional={"hostname": "fallback", "connect_timeout_ms": 99},
    )
    assert result is not None
    assert result.hostname == "fallback"
    assert result.connect_timeout_ms == 99


def test_try_load_section_works_with_runtime_config_wrapper() -> None:
    runtime = RuntimeConfig(
        {"wifi.ssid": "Net", "wifi.password": "pw"},
    )
    result = try_load_section(
        _ExampleConfig, runtime,
        prefix="wifi", required=("ssid", "password"),
    )
    assert result is not None
    assert result.ssid == "Net"


# ---------------------------------------------------------------------------
# load_runtime_config: file IO
# ---------------------------------------------------------------------------


def test_default_path_constant_is_root_runtime_config_msgpack() -> None:
    """Guard the path against accidental drift. The on-device file ABI depends on it."""
    assert DEFAULT_RUNTIME_CONFIG_PATH == "/runtime_config.msgpack"


if _IS_CPYTHON:
    # Pytest-fixture-using tests. Only collected under CPython where
    # the harness supports `tmp_path` / `monkeypatch`.

    def test_load_runtime_config_round_trips_a_flat_payload(tmp_path) -> None:
        """A msgpack file written + read back yields the same flat dict."""
        payload = {
            "wifi.ssid": "HomeNet",
            "wifi.password": "secret",
            "mqtt.broker.host": "mqtt.local",
            "mqtt.broker.port": 1883,
            "app.sample_period_ms": 5000,
        }
        path = str(tmp_path / "runtime_config.msgpack")
        with open(path, "wb") as handle:
            handle.write(packb(payload))
        loaded = load_runtime_config(path)
        assert isinstance(loaded, RuntimeConfig)
        for key, value in payload.items():
            assert loaded[key] == value

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

    def test_load_runtime_config_truncated_payload_raises_invalid_type(tmp_path) -> None:
        """A power-loss-truncated file fails as ``InvalidConfigType``, not a raw decode error.

        ``unpackb`` rejects malformed framing with ``ValueError``.
        ``load_runtime_config`` maps that onto its documented surface so
        callers (and the boot path) see one corrupt-config exception.
        """
        path = str(tmp_path / "truncated.msgpack")
        with open(path, "wb") as handle:
            handle.write(b"\xc4\xc8\x01\x02")  # bin8 claims 200 bytes, 2 given
        with raises(InvalidConfigType):
            load_runtime_config(path)

    def test_load_runtime_config_default_path_used_when_unspecified(
        monkeypatch, tmp_path,
    ) -> None:
        """Calling without an arg reads from ``DEFAULT_RUNTIME_CONFIG_PATH``."""
        seed_path = str(tmp_path / "seeded.msgpack")
        with open(seed_path, "wb") as handle:
            handle.write(packb({"app.key": "value"}))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        loaded = load_runtime_config()
        assert loaded.get("app.key") == "value"

    # -----------------------------------------------------------------
    # Module-level ``config`` attribute: PEP 562 lazy load + cache.
    # -----------------------------------------------------------------

    def _reset_config_cache(monkeypatch) -> None:
        """Reset the module-level ``config`` cache so the next access reloads."""
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "_config_cache", None)
        monkeypatch.setattr(runtime_module, "_config_loaded", False)

    def test_config_attribute_lazy_loads_on_first_access(
        monkeypatch, tmp_path,
    ) -> None:
        """``config`` reads the file only when first accessed."""
        seed_path = str(tmp_path / "seeded.msgpack")
        payload = {"wifi.ssid": "Net", "wifi.password": "pw"}
        with open(seed_path, "wb") as handle:
            handle.write(packb(payload))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        _reset_config_cache(monkeypatch)

        from chumicro_config import config
        assert config is not None
        assert config["wifi.ssid"] == "Net"

    def test_config_attribute_caches_after_first_access(
        monkeypatch, tmp_path,
    ) -> None:
        """Subsequent accesses don't re-read the file."""
        seed_path = str(tmp_path / "seeded.msgpack")
        with open(seed_path, "wb") as handle:
            handle.write(packb({"wifi.ssid": "First"}))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        _reset_config_cache(monkeypatch)

        from chumicro_config import config as first
        assert first["wifi.ssid"] == "First"

        with open(seed_path, "wb") as handle:
            handle.write(packb({"wifi.ssid": "Second"}))

        from chumicro_config import config as second
        assert second["wifi.ssid"] == "First"

    def test_config_is_none_when_file_missing(monkeypatch, tmp_path) -> None:
        """A missing file resolves to ``config = None``, not OSError."""
        missing = str(tmp_path / "nope.msgpack")
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", missing)
        _reset_config_cache(monkeypatch)

        from chumicro_config import config
        assert config is None

    def test_config_propagates_invalid_type(monkeypatch, tmp_path) -> None:
        """A malformed payload propagates ``InvalidConfigType`` on first access."""
        path = str(tmp_path / "bad.msgpack")
        with open(path, "wb") as handle:
            handle.write(packb([1, 2, 3]))  # list, not dict
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", path)
        _reset_config_cache(monkeypatch)

        with raises(InvalidConfigType):
            from chumicro_config import config  # noqa: F401

    def test_unknown_attribute_raises_attribute_error() -> None:
        """``__getattr__`` only handles ``config``. Everything else raises."""
        import chumicro_config
        with raises(AttributeError):
            chumicro_config.does_not_exist  # noqa: B018
