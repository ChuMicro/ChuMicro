"""Read the settings file ``/runtime_config.msgpack`` on the board.

The file holds one msgpack dict with dotted keys, such as
``{"wifi.ssid": "HomeNet"}``.

``config`` is a module attribute, also importable as
``chumicro_config.config``. Its first access calls
``load_runtime_config()`` and keeps the result: a ``RuntimeConfig``, or
``None`` when the file does not exist. A damaged file raises
``InvalidConfigType`` on every access instead of reading as ``None``.
"""

import errno
import gc

from chumicro_msgpack import unpackb

from chumicro_config.section import InvalidConfigType, RuntimeConfig

DEFAULT_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"
"""File ``load_runtime_config()`` reads when called without ``path``."""


def load_runtime_config(path: str | None = None) -> RuntimeConfig:
    """Read the settings file at ``path`` and return its settings as a ``RuntimeConfig``.

    ``load_runtime_config()`` reads the file on every call. A program calls
    it once at startup and passes the result to each ``from_config``.

    Args:
        path: File to read. ``None`` reads ``DEFAULT_RUNTIME_CONFIG_PATH``.

    Returns:
        A ``RuntimeConfig`` over the file's settings.

    Raises:
        OSError: The file is missing or cannot be read.
        InvalidConfigType: The file is not valid msgpack or does not unpack
            to a dict.
    """
    if path is None:
        path = DEFAULT_RUNTIME_CONFIG_PATH
    with open(path, "rb") as handle:
        payload = handle.read()
    try:
        decoded = unpackb(payload)
    except ValueError as error:
        raise InvalidConfigType(
            f"runtime config is not valid msgpack: {error}"
        ) from error
    if not isinstance(decoded, dict):
        raise InvalidConfigType(
            f"runtime config must decode to a dict, got {type(decoded).__name__}"
        )
    result = RuntimeConfig(decoded)
    # The raw file bytes are dead weight once decoded. Collecting now hands
    # that heap back during boot.
    del payload, decoded
    gc.collect()
    return result


_config_cache: RuntimeConfig | None = None
_config_loaded: bool = False


def _ensure_config_loaded() -> RuntimeConfig | None:
    global _config_cache, _config_loaded
    if not _config_loaded:
        try:
            _config_cache = load_runtime_config()
        except OSError as error:
            # A missing file (ENOENT) means no config. Any other OSError propagates.
            if not error.args or error.args[0] != errno.ENOENT:
                raise
            _config_cache = None
        _config_loaded = True
    return _config_cache


def __getattr__(name: str):
    if name == "config":
        return _ensure_config_loaded()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
