"""Runtime-config helpers: section loader and on-device reader.

The public entry points are :data:`config`, :func:`load_runtime_config`,
:func:`load_section`, and :func:`try_load_section`.
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
    # Lazy imports keep runtime (and chumicro_msgpack) out of RAM until used.
    if name == "config":
        from chumicro_config.runtime import config  # noqa: PLC0415

        return config
    if name == "load_runtime_config":
        from chumicro_config.runtime import load_runtime_config  # noqa: PLC0415

        return load_runtime_config
    if name == "runtime":
        import chumicro_config.runtime as runtime_module  # noqa: PLC0415

        return runtime_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
