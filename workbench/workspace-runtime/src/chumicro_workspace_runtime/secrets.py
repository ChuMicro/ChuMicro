"""``!secret <name>`` reference resolution.

Per Decision 0035 §5: secrets are resolved at deploy time so the
on-device payload contains only the resolved values, never the
``!secret`` markers themselves.  The marker syntax is plain string
prefix — ``"!secret wifi_password"`` — chosen so it round-trips
through TOML / YAML / JSON without needing a custom loader hook.

Walks dict / list / tuple containers recursively.  Strings that
match the ``!secret <name>`` pattern get replaced with the named
value from the secrets dict; everything else passes through
unchanged.
"""

from __future__ import annotations

_SECRET_PREFIX = "!secret "


class UnresolvedSecretError(KeyError):
    """A ``!secret <name>`` reference points at a key not in the secrets dict.

    Subclass of ``KeyError`` so callers can ``except KeyError`` if
    they prefer the standard exception, but distinct enough to
    catch specifically when downstream code wants to surface the
    failed reference cleanly.
    """


def resolve_secrets(value: object, secrets: dict[str, object]) -> object:
    """Walk *value* + replace any ``!secret <name>`` strings.

    Args:
        value: Arbitrary nested structure (dict, list, tuple, scalar).
        secrets: Map of secret name → resolved value (typically read
            from ``secrets.yml``).

    Returns:
        A new structure with the same shape as *value*, with any
        ``!secret <name>`` strings replaced by the corresponding
        secrets-dict value.  Containers are deep-copied so the
        original *value* isn't mutated.

    Raises:
        UnresolvedSecretError: A ``!secret <name>`` reference's name
            isn't a key in *secrets*.
    """
    if isinstance(value, str):
        if value.startswith(_SECRET_PREFIX):
            secret_name = value[len(_SECRET_PREFIX):].strip()
            if secret_name not in secrets:
                raise UnresolvedSecretError(
                    f"unresolved secret reference: {value!r}"
                )
            return secrets[secret_name]
        return value
    if isinstance(value, dict):
        return {key: resolve_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_secrets(item, secrets) for item in value)
    return value
