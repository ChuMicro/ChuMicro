"""Compose-time flattening for the runtime-config pipeline.

Nested ``[wifi]`` / ``[mqtt.broker]`` TOML tables on disk are the
beginner-readable shape; the device-side runtime works with a flat
dotted-key dict (``"wifi.ssid"``, ``"mqtt.broker.host"``).  Flattening
happens once at compose time so the on-disk format optimises for
human readability and the wire / device format optimises for memory
on a 256 KB-RAM target — single hash lookup per key, no recursion.

:func:`flatten_config` is the lone public function — pure, no I/O,
deterministic.  ``compose_runtime_config`` calls it after the deep
merge, so :class:`WithRuntimeConfig` writes the flat shape into
``runtime_config.msgpack`` and on-device readers see it directly.
"""

from __future__ import annotations

from typing import Any


def flatten_config(nested: dict, *, _prefix: str = "") -> dict[str, Any]:
    """Return a flat dotted-key copy of *nested*.

    Walks *nested* recursively; each non-dict leaf value lands at
    ``"<dotted.path>"`` in the result.  Empty dicts are dropped (no
    key is emitted for an inner table that has no leaf descendants).
    Lists / tuples / scalars are taken verbatim — the per-key value
    isn't recursed into, only nested dicts are.

    Args:
        nested: Source dict — typically the deep-merge of
            ``secrets.toml`` defaults and per-project overrides.
        _prefix: Internal; used during recursion to accumulate the
            dotted-path key.  External callers always omit it.

    Returns:
        A new flat dict.  Original *nested* is not mutated.

    Raises:
        ValueError: A nested key isn't a string — runtime config keys
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
