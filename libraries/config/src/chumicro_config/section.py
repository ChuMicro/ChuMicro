"""Flat-key runtime-config wrapper + section-loading helpers.

The on-device runtime config is a **flat dict** with dotted keys::

    {"wifi.ssid": "Things Cat",
     "wifi.password": "...",
     "mqtt.broker.host": "test.mosquitto.org",
     "mqtt.broker.port": 1883}

Compose-time (host-side) flattening turns nested ``[wifi]``/``[mqtt]``
TOML tables into dotted keys before they reach the msgpack wire
format.  On device, ``chumicro_config.config`` exposes that flat dict
through :class:`RuntimeConfig` — a small dict-like wrapper with
beginner-friendly accessors:

* ``config.get("wifi.ssid")`` → value or ``None`` on miss.
* ``config.get("wifi.ssid", default)`` → value or *default* on miss.
* ``config["wifi.ssid"]`` → value or :class:`MissingConfigKey` on miss.
* ``config.require("wifi.ssid")`` → value or :class:`MissingConfigKey`
  on miss.  Same as ``[]`` today; library code uses ``require`` to
  signal intent (the key is mandatory) and gives the validator a
  hook to attach declared-by context to the error message.

:func:`load_section` / :func:`try_load_section` build typed
``<Name>Config`` instances by reading dotted keys with a shared
prefix.  Each library's ``<Name>Config.from_config`` /
``try_from_config`` classmethods wrap them so the required /
optional vocabulary lives in one place.
"""


class ConfigError(Exception):
    """Base for every ``chumicro-config`` failure.

    Catch this to handle every config-specific failure uniformly.
    Catch :class:`MissingConfigKey` / :class:`InvalidConfigType`
    individually for targeted recovery.
    """


class MissingConfigKey(ConfigError):
    """A required config key was missing.

    Single-inheritance only — MicroPython rejects multiple inheritance
    from ``Exception`` subclasses with differing memory layouts, so
    ``KeyError`` (the natural second parent on CPython) isn't a base.
    Callers that want broader catching use ``except ConfigError``.
    """


class InvalidConfigType(ConfigError):
    """A config value had the wrong shape — typically the wire payload
    decoded to something other than a dict.

    Single-inheritance for the same MP reason as
    :class:`MissingConfigKey`.
    """


class RuntimeConfig:
    """Flat-key dict-like view over the deployed runtime config.

    Wraps the dict decoded from ``/runtime_config.msgpack`` so beginner
    access patterns work the way Python users expect:

    * ``config.get(key)`` returns ``None`` for missing keys.
    * ``config.get(key, default)`` returns *default* for missing keys.
    * ``config[key]`` raises :class:`MissingConfigKey` on miss.
    * ``config.require(key)`` raises :class:`MissingConfigKey` on miss.
    * ``key in config`` checks membership.
    * Iteration yields keys (like a plain dict).

    Constructed with a flat dict whose keys are dotted strings
    (``"wifi.ssid"``, ``"mqtt.broker.host"``).  Compose-time flattening
    on the host produces this shape; the device-side reader unwraps
    the msgpack and hands the dict to this constructor.
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = dict(data) if data else {}

    def get(self, key, default=None):
        """Return ``self[key]`` if present, else *default* (or ``None``)."""
        return self._data.get(key, default)

    def require(self, key):
        """Return ``self[key]`` or raise :class:`MissingConfigKey`.

        Library code uses this to express "this key is mandatory" —
        equivalent to ``self[key]`` today.  The dedicated method gives
        downstream tooling (e.g. deploy-time manifest validators) a
        clean hook to wrap the error with declared-by context.
        """
        if key not in self._data:
            raise MissingConfigKey(
                f"required config key {key!r} is missing",
            )
        return self._data[key]

    def __getitem__(self, key):
        if key not in self._data:
            raise MissingConfigKey(
                f"required config key {key!r} is missing",
            )
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __eq__(self, other):
        if isinstance(other, RuntimeConfig):
            return self._data == other._data
        if isinstance(other, dict):
            return self._data == other
        return NotImplemented

    def __repr__(self):
        return f"RuntimeConfig({self._data!r})"

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def to_dict(self) -> dict:
        """Return a shallow copy of the underlying flat dict."""
        return dict(self._data)


def load_section(
    target_class: type,
    config,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object:
    """Build *target_class* by reading flat keys with a shared *prefix*.

    Reads ``f"{prefix}.{key}"`` for each name in *required* / *optional*,
    then calls ``target_class(**kwargs)`` with the per-subkey values
    found.  The library's ``<Name>Config.from_config`` classmethod
    typically wraps this with its declared required / optional vocabulary.

    Args:
        target_class: Class to instantiate.  Called as
            ``target_class(**kwargs)`` where each kwarg name is the
            *subkey* (no prefix) and the value comes from
            ``config[f"{prefix}.{subkey}"]``.
        config: A :class:`RuntimeConfig` or plain dict carrying flat
            dotted keys.  ``None`` raises :class:`InvalidConfigType` —
            soft "config not deployed" handling belongs in
            :func:`try_load_section`, not here.
        prefix: Key prefix without a trailing dot (e.g. ``"wifi"``).
            Each required / optional subkey is joined as
            ``f"{prefix}.{subkey}"``.
        required: Tuple of subkey names that must be present.
        optional: Mapping of subkey name → default value used when the
            full key is absent from *config*.

    Raises:
        InvalidConfigType: *config* is ``None`` or not a mapping.
        MissingConfigKey: A required key is absent from *config*.
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
    config,
    *,
    prefix: str,
    required: tuple = (),
    optional: dict | None = None,
) -> object | None:
    """Soft-load — return ``None`` whenever :func:`load_section` would raise.

    Use this when a caller wants to gate test or app code on
    "config is configured for this section" without writing a
    try/except block.  Three short-circuit "skip" paths return
    ``None``:

    * *config* is ``None`` (no ``/runtime_config.msgpack`` deployed).
    * *config* is not a RuntimeConfig / dict.
    * Any required key is missing from *config*.

    Args:
        target_class: Class to instantiate when the prefix's keys
            are all present — same role as in :func:`load_section`.
        config: A :class:`RuntimeConfig`, plain dict, or ``None``.
        prefix: Key prefix without a trailing dot (e.g. ``"wifi"``).
        required: Tuple of subkey names that must be present.
        optional: Mapping of subkey name → default value.

    Returns:
        Instance of *target_class*, or ``None`` if any short-circuit
        path fired.
    """
    if config is None or not _is_config_like(config):
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


def _is_config_like(value) -> bool:
    """True when *value* supports ``key in value`` and ``value[key]``."""
    return isinstance(value, (RuntimeConfig, dict))
