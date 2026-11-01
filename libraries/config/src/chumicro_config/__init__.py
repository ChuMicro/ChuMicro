"""Read a project's settings on the board and build objects from them.

The settings form one flat dict whose keys are dotted names such as
``"wifi.ssid"``. ``load_runtime_config()`` reads them from the board into a
``RuntimeConfig``. ``load_section`` and ``try_load_section`` build an
instance of a class from the settings under one prefix.
"""

import gc

from chumicro_config.section import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    RuntimeConfig,
    load_section,
    try_load_section,
)

__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: the runtime symbols
    # below are PEP-562 lazy via __getattr__.
    "ConfigError",
    "InvalidConfigType",
    "MissingConfigKey",
    "RuntimeConfig",
    "config",
    "load_runtime_config",
    "load_section",
    "try_load_section",
]


def __getattr__(name: str):
    # The first access imports chumicro_config.runtime and chumicro_msgpack,
    # so a program that never reads the settings file never loads either.
    if name == "config":
        from chumicro_config.runtime import config  # noqa: PLC0415

        return config
    if name == "load_runtime_config":
        from chumicro_config.runtime import load_runtime_config  # noqa: PLC0415

        return load_runtime_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
