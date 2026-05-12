"""Flat-key runtime-config wrapper + section-loading helpers.

The on-device runtime config is a flat dict with dotted keys
(``"wifi.ssid"``, ``"mqtt.broker.host"``) — compose-time flattening on
the host turns nested TOML tables into this shape before the msgpack
encode.  :class:`RuntimeConfig` wraps that dict for keyed access;
:func:`load_section` / :func:`try_load_section` build typed
``<Name>Config`` instances from it.
"""


class ConfigError(Exception):
    """Base for every ``chumicro-config`` failure."""


class MissingConfigKey(ConfigError):
    """A required config key was missing."""

    # Single-inheritance only: MicroPython rejects multiple inheritance
    # from Exception subclasses with differing memory layouts, so
    # KeyError isn't a base.  Catch via ConfigError for broad handling.


class InvalidConfigType(ConfigError):
    """A config value had the wrong shape (typically not a dict)."""

    # Single-inheritance for the same MP reason as MissingConfigKey.


class RuntimeConfig:
    """Flat-key lookup wrapper over the deployed runtime config.

    Supports ``config.get(key[, default])``, ``config[key]`` /
    ``config.require(key)`` (raises :class:`MissingConfigKey` on miss),
    and ``key in config``.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = data if data is not None else {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def require(self, key):
        if key not in self._data:
            raise MissingConfigKey(
                f"required config key {key!r} is missing",
            )
        return self._data[key]

    def __getitem__(self, key):
        return self.require(key)

    def __contains__(self, key):
        return key in self._data


def is_config_like(value) -> bool:
    """Return ``True`` when *value* is a :class:`RuntimeConfig` or plain dict.

    The input gate :func:`load_section` applies internally — call it
    explicitly at the top of any consumer ``from_config`` that bypasses
    ``load_section`` (the client-with-injection pattern in the user
    guide), raising :class:`InvalidConfigType` on the failing branch.
    """
    return isinstance(value, (RuntimeConfig, dict))


def load_section(
    target_class: type,
    config: object,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object:
    """Build *target_class* by reading flat keys with a shared *prefix*.

    For each name in *required* / *optional*, reads
    ``config[f"{prefix}.{name}"]`` and passes it as the keyword
    argument *name* to ``target_class(**kwargs)``.  Missing required
    keys raise :class:`MissingConfigKey`; a *config* that isn't a
    :class:`RuntimeConfig` / dict raises :class:`InvalidConfigType`.
    Soft "config not deployed" handling belongs in
    :func:`try_load_section`.
    """
    if config is None:
        raise InvalidConfigType(
            "load_section requires a runtime config; got None",
        )
    if not is_config_like(config):
        raise InvalidConfigType(
            f"load_section requires a RuntimeConfig or dict, "
            f"got {type(config).__name__}",
        )

    optional_keys = optional if optional is not None else {}
    kwargs = {}

    for subkey in required:
        full_key = f"{prefix}.{subkey}" if prefix else subkey
        if full_key not in config:
            raise MissingConfigKey(
                f"required config key {full_key!r} is missing",
            )
        kwargs[subkey] = config[full_key]

    for subkey, default in optional_keys.items():
        full_key = f"{prefix}.{subkey}" if prefix else subkey
        if full_key in config:
            kwargs[subkey] = config[full_key]
        else:
            kwargs[subkey] = default

    return target_class(**kwargs)


def try_load_section(
    target_class: type,
    config: object,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object | None:
    """Soft-load — return ``None`` whenever :func:`load_section` would raise.

    Three skip-paths return ``None``: *config* is ``None`` (no
    runtime config deployed), *config* is the wrong type, or a required
    key is missing.  Treat the ``None`` return as "this section isn't
    configured; skip the feature."
    """
    if config is None or not is_config_like(config):
        return None
    try:
        return load_section(
            target_class,
            config,
            prefix=prefix,
            required=required,
            optional=optional,
        )
    except (MissingConfigKey, InvalidConfigType):
        return None
