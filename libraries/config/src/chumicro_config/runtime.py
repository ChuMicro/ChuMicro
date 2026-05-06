"""On-device reader for ``/runtime_config.msgpack``.

Two surfaces:

* :data:`config` — the loaded :class:`RuntimeConfig` (or ``None``
  when the file is missing).  Lazy-loaded on first attribute access
  via PEP 562 module-level ``__getattr__``: the file isn't read
  until something actually touches ``config``, and the result is
  cached for the lifetime of the import.  Apps gate on
  ``if config is None:`` to handle the no-deployed-config path;
  per-key access reads values: ``config["wifi.ssid"]`` (raises
  :class:`MissingConfigKey` on miss) or ``config.get("wifi.ssid")``
  (returns ``None`` on miss).
* :func:`load_runtime_config` — the explicit reader; raises
  ``OSError`` on missing file, :class:`InvalidConfigType` on
  malformed payload.  Returns a :class:`RuntimeConfig` directly so
  callers don't have to re-wrap.  Used when a caller needs precise
  error semantics, wants to re-read after a deploy, or reads a
  non-default path.

The on-device payload is always the **flat** dotted-key shape
produced by ``chumicro_workspace.compose_runtime_config`` — nested
``[wifi]`` / ``[mqtt]`` TOML tables on disk become
``"wifi.ssid"`` / ``"mqtt.broker.host"`` flat keys at compose time.
"""

from chumicro_msgpack import unpackb

from chumicro_config.section import InvalidConfigType, RuntimeConfig

DEFAULT_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"
"""Canonical on-device location of the deployed runtime config.

Changing this is an ABI break for every library + every workspace
template — don't.
"""


def load_runtime_config(path: str | None = None) -> RuntimeConfig:
    """Read + decode the deployed runtime config.

    Args:
        path: On-device path to the msgpack file.  ``None`` (default)
            resolves to :data:`DEFAULT_RUNTIME_CONFIG_PATH` at call
            time — the indirection lets tests monkey-patch the
            constant without losing the default-arg ergonomics.

    Returns:
        A :class:`RuntimeConfig` wrapping the decoded flat dict.

    Raises:
        OSError: File missing — device was deployed without a
            ``/runtime_config.msgpack``, or the path is wrong.
        InvalidConfigType: Decoded payload isn't a dict (corrupted
            file or wrong shape).
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
    """Load + cache the runtime config on first call; return the cached value."""
    global _config_cache, _config_loaded
    if not _config_loaded:
        try:
            _config_cache = load_runtime_config()
        except OSError:
            _config_cache = None
        _config_loaded = True
    return _config_cache


def __getattr__(name: str):
    """Lazy-load ``config`` on first attribute access (PEP 562).

    ``InvalidConfigType`` (file present but malformed) is **not**
    caught — corruption is a hard deploy failure, surfaced loudly
    on first access rather than silently masked as ``config = None``.
    """
    if name == "config":
        return _ensure_config_loaded()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
