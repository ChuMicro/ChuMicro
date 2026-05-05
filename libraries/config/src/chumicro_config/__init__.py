"""Standardized runtime-config helpers for ChuMicro libraries.

Public API::

    from chumicro_config import (
        config,                     # the loaded /runtime_config.msgpack dict (or None)
        load_runtime_config,        # explicit reader — raises on missing
        load_section,               # build a typed Config from a dict slice
        ConfigError,                # base exception
        InvalidConfigType,          # section value isn't a dict
        MissingConfigKey,           # required key absent from a section
    )

Typical user-app pattern::

    from chumicro_config import config

    if config is None:
        return  # no runtime config deployed — skip / use defaults

    wifi = WifiService(WifiConfig.from_dict(config["wifi"]))

``config`` is lazy-loaded on first access (PEP 562) and cached for
the lifetime of the import.  Apps that import :mod:`chumicro_config`
solely for :class:`InvalidConfigType` / :func:`load_section` pay no
file-read cost.

Typical library-side pattern (inside ``WifiConfig.from_dict``)::

    return load_section(
        cls,
        data,
        required=("ssid", "password"),
        optional={"hostname": None, "connect_timeout_ms": 15_000},
    )
"""

from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config
from chumicro_config.section import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    load_section,
    try_load_section,
)

__all__ = [
    "DEFAULT_RUNTIME_CONFIG_PATH",
    "ConfigError",
    "InvalidConfigType",
    "MissingConfigKey",
    "config",
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


# `chumicro_config.templates` ships separately because `importlib.resources`
# is CPython-only — workspace tooling on the host imports it, device code
# never does.  Not re-exported here so a stray `from chumicro_config import
# templates` on a device fails fast rather than mid-call.
