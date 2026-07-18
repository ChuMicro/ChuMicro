"""On-device reader for ``/runtime_config.msgpack`` (flat dotted-key shape)."""

import errno

from chumicro_msgpack import unpackb

from chumicro_config.section import InvalidConfigType, RuntimeConfig

DEFAULT_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"
"""Default on-device location of the runtime config file."""


def load_runtime_config(path: str | None = None) -> RuntimeConfig:
    """Read and decode the deployed runtime config file.

    Args:
        path: File to read; defaults to
            :data:`DEFAULT_RUNTIME_CONFIG_PATH`.

    Returns:
        The decoded config wrapped in a :class:`RuntimeConfig`.

    Raises:
        OSError: The file is missing or unreadable.
        InvalidConfigType: The payload is not valid msgpack or does not
            decode to a dict.
    """
    if path is None:
        path = DEFAULT_RUNTIME_CONFIG_PATH
    with open(path, "rb") as handle:
        try:
            decoded = unpackb(handle.read())
        except ValueError as error:
            raise InvalidConfigType(
                f"runtime config is not valid msgpack: {error}"
            ) from error
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
        except OSError as error:
            # A missing file (ENOENT) means "no config"; other OSErrors surface.
            if error.args and error.args[0] != errno.ENOENT:
                raise
            _config_cache = None
        _config_loaded = True
    return _config_cache


def __getattr__(name: str):
    # Malformed config (InvalidConfigType) is a hard failure, never a silent None.
    if name == "config":
        return _ensure_config_loaded()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
