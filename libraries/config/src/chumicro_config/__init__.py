"""Runtime-config helpers: section loader + on-device reader.

Apps import :data:`config` (lazy-loaded ``/runtime_config.msgpack``,
or ``None`` when absent) or :func:`load_runtime_config` for the
explicit read.  Library authors use :func:`load_section` /
:func:`try_load_section` to build typed ``<Name>Config`` instances.
Patterns and exceptions live in ``docs/guide.md``.
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
    # pyright: ignore[reportUnsupportedDunderAll] — the runtime symbols
    # below are PEP-562 lazy via __getattr__.
    "DEFAULT_RUNTIME_CONFIG_PATH",
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
    """Lazy-load the runtime reader on first access (PEP 562).

    ``runtime`` imports ``chumicro_msgpack`` at module scope, so keeping
    ``config`` / ``load_runtime_config`` / ``DEFAULT_RUNTIME_CONFIG_PATH``
    out of the eager import path means a library that only uses
    ``load_section`` never drags the msgpack decoder into RAM.
    """
    if name == "config":
        from chumicro_config.runtime import config  # noqa: PLC0415

        return config
    if name == "load_runtime_config":
        from chumicro_config.runtime import load_runtime_config  # noqa: PLC0415

        return load_runtime_config
    if name == "DEFAULT_RUNTIME_CONFIG_PATH":
        from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH  # noqa: PLC0415

        return DEFAULT_RUNTIME_CONFIG_PATH
    if name == "runtime":
        import chumicro_config.runtime as runtime_module  # noqa: PLC0415

        return runtime_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
