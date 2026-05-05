"""Standardized ``from_dict`` factory + exception hierarchy.

``load_section`` is the canonical implementation every
config-consuming library's ``<Name>Config.from_dict`` calls.  Locks
in missing-required / missing-optional / unknown-key semantics so
libraries can't drift.
"""


class ConfigError(Exception):
    """Base for every ``chumicro-config`` failure.

    Catch this to handle every config-specific failure uniformly.
    Catch :class:`MissingConfigKey` / :class:`InvalidConfigType`
    individually for targeted recovery.
    """


class MissingConfigKey(ConfigError):
    """A required config key was missing from the section dict.

    Single-inheritance only — MP rejects multiple inheritance from
    ``Exception`` subclasses with differing memory layouts, so
    ``KeyError`` (the natural second parent on CPython) isn't a
    base.  Callers that want broader catching use ``except
    ConfigError``.
    """


class InvalidConfigType(ConfigError):
    """The section value wasn't a dict (caller passed something else).

    Single-inheritance for the same MP reason as
    :class:`MissingConfigKey` (no ``TypeError`` second parent).
    """


def load_section(
    target_class: type,
    data: object,
    *,
    required: tuple = (),
    optional: dict | None = None,
) -> object:
    """Build *target_class* from a config-dict slice.

    Behaviors:

    * Missing required key → :class:`MissingConfigKey`.
    * Missing optional key → default from *optional* mapping.
    * *data* is not a dict → :class:`InvalidConfigType`.
    * Unknown keys are ignored (forward-compat).
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


def try_load_section(
    target_class: type,
    runtime_config: dict | None,
    section_name: str,
    *,
    required: tuple = (),
    optional: dict | None = None,
) -> object | None:
    """Soft-load a section from the runtime config.  Returns ``None`` on miss.

    Unlike :func:`load_section`, the input is the **whole runtime
    config dict** (the value of ``chumicro_config.config``), not a
    pre-extracted section.  Three short-circuit "skip" paths return
    ``None`` instead of raising:

    * *runtime_config* is ``None`` (no ``/runtime_config.msgpack``
      deployed — fresh-clone state on a board with no creds yet).
    * The named section is absent from *runtime_config*, or its
      value isn't a dict.
    * The section is present but a required key is missing or the
      value isn't a dict (mirrors :class:`MissingConfigKey` /
      :class:`InvalidConfigType`).

    Use this when a caller wants to gate test or app code on
    "config is configured for this section" without writing a
    try/except block.  The canonical pattern is a per-library
    ``Config.try_from_dict`` classmethod that wraps this helper —
    see :class:`chumicro_wifi.WifiConfig.try_from_dict`.

    Args:
        target_class: Class to instantiate when the section is
            present + valid — same role as in :func:`load_section`.
        runtime_config: The whole runtime config dict (typically
            ``chumicro_config.config``), or ``None``.
        section_name: Top-level key in *runtime_config* whose value
            holds the per-library section dict.
        required: Tuple of key names that must be present in the
            section.  Missing keys → ``None`` return (not raise).
        optional: Mapping of key name → default value.

    Returns:
        Instance of *target_class*, or ``None`` if any short-circuit
        path fired.
    """
    if runtime_config is None:
        return None
    section = runtime_config.get(section_name)
    if not isinstance(section, dict):
        return None
    try:
        return load_section(
            target_class, section, required=required, optional=optional,
        )
    except (MissingConfigKey, InvalidConfigType):
        return None
