"""Runtime-config helpers — section loader + on-device reader.

Apps import :data:`config` (lazy-loaded ``/runtime_config.msgpack``,
or ``None`` when absent) or :func:`load_runtime_config` for the
explicit read.  Library authors use :func:`load_section` /
:func:`try_load_section` to build typed ``<Name>Config`` instances.
Patterns and exceptions live in ``docs/guide.md``.
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
