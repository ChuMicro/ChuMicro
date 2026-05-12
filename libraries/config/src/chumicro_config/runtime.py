"""On-device reader for ``/runtime_config.msgpack`` (flat dotted-key shape)."""

from chumicro_msgpack import unpackb

from chumicro_config.section import InvalidConfigType, RuntimeConfig

DEFAULT_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"
"""Canonical on-device location — changing this is an ABI break."""


def load_runtime_config(path: str | None = None) -> RuntimeConfig:
    """Read + decode the deployed runtime config.

    Raises ``OSError`` if the file is missing, :class:`InvalidConfigType`
    if the payload isn't a dict.  *path* defaults to
    :data:`DEFAULT_RUNTIME_CONFIG_PATH` at call time (resolved late so
    tests can monkey-patch the constant).
    """
    if path is None:
        path = DEFAULT_RUNTIME_CONFIG_PATH
    with open(path, "rb") as handle:
        decoded = unpackb(handle.read())
    if not isinstance(decoded, dict):
        raise InvalidConfigType(
            f"runtime config must decode to a dict, got {type(decoded).__name__}"
        )
    return RuntimeConfig(decoded)


_config_cache: RuntimeConfig | None = None
_config_loaded: bool = False


def _ensure_config_loaded() -> RuntimeConfig | None:
    global _config_cache, _config_loaded
    if not _config_loaded:
        try:
            _config_cache = load_runtime_config()
        except OSError:
            _config_cache = None
        _config_loaded = True
    return _config_cache


def __getattr__(name: str):
    # `InvalidConfigType` (file present but malformed) is intentionally
    # not caught here — corruption is a hard deploy failure, surfaced
    # loudly rather than silently masked as `config = None`.
    if name == "config":
        return _ensure_config_loaded()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
