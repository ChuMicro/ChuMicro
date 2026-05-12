"""Standardized runtime-config helpers for ChuMicro libraries.

Public API::

    from chumicro_config import (
        config,                     # the loaded /runtime_config.msgpack RuntimeConfig (or None)
        load_runtime_config,        # explicit reader — raises on missing file
        load_section,               # build a typed Config from flat keys with a shared prefix
        try_load_section,           # soft-load sibling — returns None on miss
        RuntimeConfig,              # flat-key dict-like wrapper (see section.py)
        ConfigError,                # base exception
        InvalidConfigType,          # payload had the wrong shape
        MissingConfigKey,           # required key absent
    )

Typical user-app pattern::

    from chumicro_config import config

    if config is None:
        return  # no runtime config deployed — skip / use defaults

    wifi = WifiService(WifiConfig.from_config(config))

``config`` is lazy-loaded on first access (PEP 562) and cached for
the lifetime of the import.  Apps that import :mod:`chumicro_config`
solely for :class:`InvalidConfigType` / :func:`load_section` pay no
file-read cost.

Per-key access::

    ssid = config.get("wifi.ssid")            # None on miss
    hold = config.get("button.hold_ms", 5000)  # default fallback
    broker = config["mqtt.broker.host"]        # raises MissingConfigKey on miss
    broker = config.require("mqtt.broker.host")  # same as [], named for intent

Typical library-side pattern (inside ``WifiConfig.from_config``)::

    return load_section(
        cls,
        config,
        prefix="wifi",
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
"""

from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config
from chumicro_config.section import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    RuntimeConfig,
    load_section,
    try_load_section,
)

__all__ = [
    "DEFAULT_RUNTIME_CONFIG_PATH",
    "ConfigError",
    "InvalidConfigType",
    "MissingConfigKey",
    "RuntimeConfig",
    "config",  # pyright: ignore[reportUnsupportedDunderAll]  # PEP-562 lazy via __getattr__ below.
    "load_runtime_config",
    "load_section",
    "try_load_section",
]


def __getattr__(name: str):
    """Lazy-load ``config`` on first access (PEP 562 — see runtime module)."""
    if name == "config":
        from chumicro_config.runtime import config  # noqa: PLC0415

        return config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
