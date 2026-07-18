"""Runtime-config helpers: section loader and on-device reader.

Apps import :data:`config` (the lazily-loaded ``/runtime_config.msgpack``,
or ``None`` when absent) or :func:`load_runtime_config`. Library authors
use :func:`load_section` / :func:`try_load_section` to build typed
``<Name>Config`` instances. Patterns and exceptions live in
``docs/guide.md``.
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
    # Lazy PEP 562 imports: a library that only calls load_section never
    # drags runtime (and its chumicro_msgpack dependency) into RAM.
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
