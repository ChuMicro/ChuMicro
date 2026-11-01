"""``RuntimeConfig`` looks up settings, and ``load_section`` builds objects from them.

``RuntimeConfig`` answers lookups by dotted key such as ``"wifi.ssid"``.
``load_section`` and ``try_load_section`` build an instance of a class from
the settings under one prefix. ``MissingConfigKey`` and
``InvalidConfigType`` report a missing setting and an unusable config.
"""


class ConfigError(Exception):
    """Base class of ``MissingConfigKey`` and ``InvalidConfigType``.

    ``except ConfigError:`` catches both.
    """


class MissingConfigKey(ConfigError):
    """Raised when a required setting is missing.

    ``config[key]``, ``RuntimeConfig.require``, and ``load_section`` raise
    it. ``MissingConfigKey`` subclasses ``ConfigError`` only, so
    ``except KeyError:`` misses it.
    """

    # Not a KeyError subclass: MicroPython forbids multiple Exception inheritance.


class InvalidConfigType(ConfigError):
    """Raised when the settings object or settings file is unusable.

    ``load_section`` raises it for a ``config`` that is ``None`` or neither a
    ``RuntimeConfig`` nor a ``dict``. ``load_runtime_config`` raises it for a
    file that is not valid msgpack or does not unpack to a dict.
    """


class RuntimeConfig:
    """Settings lookup by dotted key, such as ``config["wifi.ssid"]``.

    ``RuntimeConfig(dict)`` builds one from a dict, so code runs without a
    settings file. ``config[key]`` works like ``require``, and
    ``key in config`` reports whether a setting exists.

    Args:
        data: Settings dict with dotted keys. ``None`` gives an empty config.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = data if data is not None else {}

    def get(self, key: str, default: object = None) -> object:
        """Return the setting for ``key``, or ``default`` when it is missing."""
        return self._data.get(key, default)

    def require(self, key: str) -> object:
        """Return the setting for ``key``.

        Raises:
            MissingConfigKey: ``key`` has no setting.
        """
        if key not in self._data:
            raise MissingConfigKey(
                f"required config key {key!r} is missing",
            )
        return self._data[key]

    def __getitem__(self, key: str) -> object:
        return self.require(key)

    def __contains__(self, key: str) -> bool:
        return key in self._data


def load_section(
    target_class: type,
    config: object,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object:
    """Build a ``target_class`` instance from the settings under ``prefix``.

    ``load_section`` reads the setting ``"<prefix>.<name>"`` for each name in
    ``required`` and ``optional``, then calls ``target_class(**values)`` with
    each bare name as a keyword argument. A missing optional setting takes its
    default. ``load_section`` ignores settings outside the two lists and
    passes values through unconverted, so ``"1883"`` stays a string. A
    class's ``from_config(config)`` class method is the usual caller.

    Args:
        target_class: Class to build. Its ``__init__`` takes each name in
            ``required`` and ``optional`` as a keyword argument.
        config: A ``RuntimeConfig`` or a plain ``dict`` with dotted keys.
        prefix: Section name, such as ``"wifi"``. An empty string reads each
            name as a bare key.
        required: Names whose settings must exist.
        optional: Names mapped to the default used when the setting is
            missing.

    Returns:
        The new ``target_class`` instance.

    Raises:
        MissingConfigKey: A name in ``required`` has no setting.
        InvalidConfigType: ``config`` is ``None`` or neither a
            ``RuntimeConfig`` nor a ``dict``.
    """
    if config is None:
        raise InvalidConfigType(
            "load_section requires a runtime config; got None",
        )
    if not isinstance(config, (RuntimeConfig, dict)):
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
    """Build a ``target_class`` instance like ``load_section``, or return ``None``.

    ``try_load_section`` returns ``None`` wherever ``load_section`` raises
    ``MissingConfigKey`` or ``InvalidConfigType``: ``config`` is ``None`` or
    the wrong type, or a required setting is missing. It suits a feature that
    runs only when its settings exist. An error raised by ``target_class``
    itself still propagates.

    Args:
        target_class: Class to build. Its ``__init__`` takes each name in
            ``required`` and ``optional`` as a keyword argument.
        config: A ``RuntimeConfig``, a plain ``dict`` with dotted keys, or
            ``None``.
        prefix: Section name, such as ``"mqtt"``. An empty string reads each
            name as a bare key.
        required: Names whose settings must exist.
        optional: Names mapped to the default used when the setting is
            missing.

    Returns:
        The new ``target_class`` instance, or ``None`` when ``config`` is
            unusable or a required setting is missing.
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
