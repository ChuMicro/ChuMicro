"""Standardized runtime-config helpers for ChuMicro libraries.

Implements the convention from Decision 0035 (runtime config file
structure) — see Decision 0036 for why this lives in its own
library.

Public API::

    from chumicro_config import (
        load_runtime_config,        # read /runtime_config.msgpack
        load_section,               # build a typed Config from a dict slice
        ConfigError,                # base exception
        InvalidConfigType,          # section value isn't a dict
        MissingConfigKey,           # required key absent from a section
    )

Typical user-app pattern::

    config = load_runtime_config()
    wifi = WifiService(WifiConfig.from_dict(config["wifi"]))

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
)

__all__ = [
    "DEFAULT_RUNTIME_CONFIG_PATH",
    "ConfigError",
    "InvalidConfigType",
    "MissingConfigKey",
    "load_runtime_config",
    "load_section",
]
