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
    try_load_section,
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
# try_load_section — soft-load wrapper (returns None instead of raising)
# ---------------------------------------------------------------------------


def test_try_load_section_returns_none_when_runtime_config_is_none() -> None:
    """``runtime_config=None`` short-circuits — no creds deployed."""
    result = try_load_section(
        _ExampleConfig, None, "wifi",
        required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_none_when_section_missing() -> None:
    """A runtime config with no matching section returns ``None``, not KeyError."""
    result = try_load_section(
        _ExampleConfig, {"mqtt": {"broker": "x"}}, "wifi",
        required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_none_when_section_not_a_dict() -> None:
    """A non-dict section value returns ``None``, not InvalidConfigType."""
    result = try_load_section(
        _ExampleConfig, {"wifi": "scalar"}, "wifi",
        required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_none_when_required_key_missing() -> None:
    """Missing required key → ``None``, not MissingConfigKey."""
    result = try_load_section(
        _ExampleConfig, {"wifi": {"ssid": "Net"}}, "wifi",
        required=("ssid", "password"),
    )
    assert result is None


def test_try_load_section_returns_instance_when_section_valid() -> None:
    """Section present + required keys present → built instance."""
    result = try_load_section(
        _ExampleConfig,
        {"wifi": {"ssid": "Net", "password": "pw"}},
        "wifi",
        required=("ssid", "password"),
    )
    assert result is not None
    assert result.ssid == "Net"
    assert result.password == "pw"


def test_try_load_section_applies_optional_defaults() -> None:
    """Optional keys that are absent receive their declared defaults."""
    result = try_load_section(
        _ExampleConfig,
        {"wifi": {"ssid": "Net", "password": "pw"}},
        "wifi",
        required=("ssid", "password"),
        optional={"hostname": "fallback", "connect_timeout_ms": 99},
    )
    assert result is not None
    assert result.hostname == "fallback"
    assert result.connect_timeout_ms == 99


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

    # -----------------------------------------------------------------
    # Module-level ``config`` attribute — PEP 562 lazy load + cache.
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
        payload = {"wifi": {"ssid": "Net", "password": "pw"}}
        with open(seed_path, "wb") as handle:
            handle.write(packb(payload))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        _reset_config_cache(monkeypatch)

        # First access triggers the load.
        from chumicro_config import config
        assert config == payload

    def test_config_attribute_caches_after_first_access(
        monkeypatch, tmp_path,
    ) -> None:
        """Subsequent accesses don't re-read the file."""
        seed_path = str(tmp_path / "seeded.msgpack")
        with open(seed_path, "wb") as handle:
            handle.write(packb({"wifi": {"ssid": "First"}}))
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", seed_path)
        _reset_config_cache(monkeypatch)

        # First access loads "First".
        from chumicro_config import config as first
        assert first["wifi"]["ssid"] == "First"

        # Mutate the file on disk; the cache should still hold the
        # original load.
        with open(seed_path, "wb") as handle:
            handle.write(packb({"wifi": {"ssid": "Second"}}))

        from chumicro_config import config as second
        assert second["wifi"]["ssid"] == "First"

    def test_config_is_none_when_file_missing(monkeypatch, tmp_path) -> None:
        """A missing file resolves to ``config = None``, not OSError."""
        missing = str(tmp_path / "nope.msgpack")
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", missing)
        _reset_config_cache(monkeypatch)

        from chumicro_config import config
        assert config is None

    def test_config_propagates_invalid_type(monkeypatch, tmp_path) -> None:
        """A malformed payload propagates ``InvalidConfigType`` on first access.

        Corruption is a hard deploy failure, not a silent skip — apps
        gating on ``if config is None:`` shouldn't silently degrade
        when the file lands corrupt.
        """
        path = str(tmp_path / "bad.msgpack")
        with open(path, "wb") as handle:
            handle.write(packb([1, 2, 3]))  # list, not dict
        import chumicro_config.runtime as runtime_module
        monkeypatch.setattr(runtime_module, "DEFAULT_RUNTIME_CONFIG_PATH", path)
        _reset_config_cache(monkeypatch)

        with raises(InvalidConfigType):
            from chumicro_config import config  # noqa: F401

    def test_unknown_attribute_raises_attribute_error() -> None:
        """``__getattr__`` only handles ``config``; everything else raises."""
        import chumicro_config
        with raises(AttributeError):
            chumicro_config.does_not_exist  # noqa: B018
