"""Standardized runtime-config helpers for ChuMicro libraries.

Exposes :data:`config` (the loaded ``/runtime_config.msgpack``, or
``None`` when no file is deployed), :func:`load_runtime_config` (the
explicit reader), :func:`load_section` / :func:`try_load_section`
(strict + soft section builders), :class:`RuntimeConfig` (the
flat-key dict wrapper), and the :class:`ConfigError` /
:class:`MissingConfigKey` / :class:`InvalidConfigType` exceptions.

:data:`config` is lazy-loaded on first attribute access (PEP 562);
apps that import this module only for the section helpers or
exception classes pay no file-read cost.  Usage patterns live in
``docs/guide.md``.
"""

from chumicro_config.runtime import DEFAULT_RUNTIME_CONFIG_PATH, load_runtime_config
from chumicro_config.section import (
    ConfigError,
    InvalidConfigType,
    MissingConfigKey,
    RuntimeConfig,
    is_config_like,
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
    "is_config_like",
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
