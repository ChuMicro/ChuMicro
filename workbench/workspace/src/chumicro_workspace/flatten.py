"""Compose-time flattening for the runtime-config pipeline.

Nested ``[wifi]`` / ``[mqtt.broker]`` TOML tables on disk are the
beginner-readable shape.  The device-side runtime works with a flat
dotted-key dict (``"wifi.ssid"``, ``"mqtt.broker.host"``).  Flattening
happens once at compose time so the on-disk format optimizes for
human readability and the wire / device format optimizes for memory
on a 256 KB-RAM target: single hash lookup per key, no recursion.

:func:`flatten_config` is pure, has no I/O, and is deterministic.
The flat shape is what writes into ``runtime_config.msgpack`` and
what on-device readers see directly.
"""

from __future__ import annotations

from typing import Any


def flatten_config(nested: dict, *, _prefix: str = "") -> dict[str, Any]:
    """Return a flat dotted-key copy of *nested*.

    Walks *nested* recursively; each non-dict leaf value lands at
    ``"<dotted.path>"`` in the result.  Empty dicts are dropped (no
    key is emitted for an inner table that has no leaf descendants).
    Lists, tuples, and scalars are taken verbatim. The per-key
    value isn't recursed into, only nested dicts are.

    Args:
        nested: Source dict to flatten.
        _prefix: Internal; used during recursion to accumulate the
            dotted-path key.

    Returns:
        A new flat dict.  Original *nested* is not mutated.

    Raises:
        ValueError: A nested key isn't a string. Runtime config keys
            must be string-typed for the dotted-path representation
            to be reversible.
    """
    flat: dict[str, Any] = {}
    for key, value in nested.items():
        if not isinstance(key, str):
            raise ValueError(
                f"runtime config key must be a string, "
                f"got {type(key).__name__}={key!r}",
            )
        full_key = f"{_prefix}.{key}" if _prefix else key
        if isinstance(value, dict):
            flat.update(flatten_config(value, _prefix=full_key))
        else:
            flat[full_key] = value
    return flat
