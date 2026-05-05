"""Deep per-key merge for the runtime-config pipeline.

Workspace defaults + per-project overrides combine **key-by-key
within sections**, with the project winning on conflict.  Sections
present only in workspace.yml carry through as global defaults the
project inherits without restating; sections present only in the
project carry through as project-specific.

Pure functions, fully deterministic — same inputs always yield the
same merged output.  No file IO; the loaders module handles that.
"""

from __future__ import annotations

import copy


def merge_configs(*sources: dict) -> dict:
    """Deep-merge two or more dicts left-to-right.

    Later sources override earlier ones key-by-key.  Nested dicts
    merge recursively; non-dict leaf values are replaced wholesale.
    Lists do **not** merge — a later source's list replaces the
    earlier source's list entirely (per ADR 0035 §5: merge is
    key-level, not element-level).

    Args:
        *sources: Two or more dicts to merge.  The leftmost is the
            base (lowest precedence); each subsequent source
            overrides the merged-so-far state.

    Returns:
        A new dict with the merged contents.  Original sources are
        not mutated.

    Raises:
        ValueError: Fewer than one source was provided.
    """
    if not sources:
        raise ValueError("merge_configs requires at least one source dict")

    merged: dict = {}
    for source in sources:
        if not isinstance(source, dict):
            raise TypeError(
                f"merge_configs sources must be dicts, got {type(source).__name__}"
            )
        merged = _merge_two(merged, source)
    return merged


def _merge_two(base: dict, override: dict) -> dict:
    """Return a new dict that is *base* recursively overlaid by *override*."""
    result = copy.deepcopy(base)
    for key, override_value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(override_value, dict)
        ):
            result[key] = _merge_two(result[key], override_value)
        else:
            result[key] = copy.deepcopy(override_value)
    return result
