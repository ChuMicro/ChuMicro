"""Standardized ``from_dict`` factory + exception hierarchy.

``load_section`` is the canonical implementation that every
config-consuming library's ``<Name>Config.from_dict`` calls.  Locks
in the behaviors Decision 0036 §2 enumerates so libraries can't
drift on missing-required vs missing-optional vs unknown-key
semantics.
"""


class ConfigError(Exception):
    """Base for every ``chumicro-config`` failure.

    Catch this to handle every config-specific failure uniformly.
    Catch :class:`MissingConfigKey` / :class:`InvalidConfigType`
    individually for targeted recovery.
    """


class MissingConfigKey(ConfigError):
    """A required config key was missing from the section dict.

    Single-inheritance from :class:`ConfigError` only — MicroPython
    doesn't allow multiple inheritance from ``Exception`` subclasses
    with different memory layouts (``KeyError`` would be the natural
    second parent), so callers that want stdlib-style catching
    should use ``except ConfigError`` instead.
    """


class InvalidConfigType(ConfigError):
    """The section value wasn't a dict (caller passed something else).

    Single-inheritance for the same MP-compatibility reason as
    :class:`MissingConfigKey` — ``TypeError`` would be the natural
    second parent on CPython.
    """


def load_section(target_class, data, *, required=(), optional=None):
    """Build *target_class* from a config-dict slice.

    The standardized ``from_dict`` core (Decision 0036 §2).  Lock-in
    behaviors:

    * Missing required key → :class:`MissingConfigKey`.
    * Missing optional key → default from *optional* mapping.
    * *data* is not a dict → :class:`InvalidConfigType`.
    * Unknown keys are ignored (Decision 0035 §7 — forward-compat).
    * No type coercion: ``"1883"`` stays a string; the target class
      ``__init__`` does any conversion.

    Args:
        target_class: Class to instantiate.  Called as
            ``target_class(**kwargs)`` with the keys this function
            extracted from *data*.
        data: The section dict — typically ``config["wifi"]``.
        required: Tuple of key names that must be present in *data*.
        optional: Mapping of key name → default value used when the
            key is absent from *data*.

    Raises:
        InvalidConfigType: *data* is not a dict.
        MissingConfigKey: A required key is missing from *data*.
    """
    if not isinstance(data, dict):
        raise InvalidConfigType(
            f"config section must be a dict, got {type(data).__name__}"
        )

    optional_keys = optional if optional is not None else {}
    kwargs = {}

    for key in required:
        if key not in data:
            raise MissingConfigKey(
                f"required config key {key!r} is missing"
            )
        kwargs[key] = data[key]

    for key, default in optional_keys.items():
        kwargs[key] = data.get(key, default)

    return target_class(**kwargs)
