"""Read the device's runtime config and pull typed sections out of it.

:class:`RuntimeConfig` wraps it for lookups; :func:`load_section` and
:func:`try_load_section` build typed sections.
"""


class ConfigError(Exception):
    """Base class for every ``chumicro-config`` error."""


class MissingConfigKey(ConfigError):
    """A required config key was not present."""

    # Not a KeyError subclass: MicroPython forbids multiple Exception inheritance.


class InvalidConfigType(ConfigError):
    """A config value had the wrong shape, usually not a dict."""


class RuntimeConfig:
    """Dict-like lookup over the deployed runtime config."""

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


def _is_config_like(value) -> bool:
    return isinstance(value, (RuntimeConfig, dict))


def load_section(
    target_class: type,
    config: object,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object:
    """Build *target_class* from flat config keys sharing a *prefix*.

    Args:
        target_class: Class to build from the collected keyword args.
        config: A :class:`RuntimeConfig` or plain dict to read from.
        prefix: Dotted prefix shared by this section's keys.
        required: Key names that must be present.
        optional: Key names mapped to the fallback used when absent.

    Returns:
        An instance of *target_class*.

    Raises:
        MissingConfigKey: A required key is missing.
        InvalidConfigType: *config* is ``None`` or not a config/dict.
    """
    if config is None:
        raise InvalidConfigType(
            "load_section requires a runtime config; got None",
        )
    if not _is_config_like(config):
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
    """Like :func:`load_section`, but return ``None`` instead of raising.

    Args:
        target_class: Class to build from the collected keyword args.
        config: A :class:`RuntimeConfig` or plain dict, or ``None``.
        prefix: Dotted prefix shared by this section's keys.
        required: Key names that must be present.
        optional: Key names mapped to the fallback used when absent.

    Returns:
        An instance of *target_class*, or ``None`` when the section is
        not configured.
    """
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
