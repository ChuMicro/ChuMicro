"""Append upstream-template keys to the user's ``workspace.yml`` /
``secrets.toml`` without clobbering edits or losing comments.

Setup re-apply is **additive only**: when the upstream template gains
a new key that the user doesn't have, append it to the user file in
place.  Existing values + surrounding comments are never touched.

Two writers:

* TOML: :mod:`tomlkit` provides comment-preserving round-trip.  The
  stdlib :mod:`tomllib` reads but can't write.
* YAML: ``ruamel.yaml`` (already a workbench dep) does the same for
  ``workspace.yml``.

Driven by :func:`additive_reapply`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomlkit
from ruamel.yaml import YAML

from chumicro_workspace.atomic_write import atomic_write_text
from chumicro_workspace.template_drift import (
    _resolve_template_text,
    collect_missing_template_paths,
)

#: Files the additive re-apply walks, in the order they are reported.
_REAPPLY_TARGETS: tuple[str, ...] = ("workspace.yml", "secrets.toml")


def additive_reapply(workspace_root: Path) -> dict[str, list[str]]:
    """For each tracked file, append upstream-template keys the user is missing.

    Returns a dict mapping filename to list of appended dotted paths.
    Files with no drift (or no user file yet) are absent from the
    returned dict.

    The user's file is rewritten in place when keys were appended;
    untouched otherwise.  Comments + ordering of existing keys are
    preserved by the underlying TOML / YAML round-trip libraries.

    Args:
        workspace_root: Workspace root containing the user files.

    Returns:
        Dict of ``filename: [dotted-paths-appended]`` for files that
        actually changed.  Empty dict when nothing drifted.
    """
    appended: dict[str, list[str]] = {}
    for filename in _REAPPLY_TARGETS:
        user_path = workspace_root / filename
        if not user_path.is_file():
            continue
        missing = collect_missing_template_paths(
            workspace_root=workspace_root, filename=filename,
        )
        if not missing:
            continue
        template_text = _resolve_template_text(filename)
        user_text = user_path.read_text(encoding="utf-8")
        if filename.endswith(".toml"):
            new_text = _append_missing_toml(user_text, template_text, missing)
        else:
            new_text = _append_missing_yaml(user_text, template_text, missing)
        atomic_write_text(user_path, new_text)
        appended[filename] = missing
    return appended


def _append_missing_toml(
    user_text: str,
    template_text: str,
    missing_paths: list[str],
) -> str:
    """Return *user_text* with each *missing* dotted path appended from *template*.

    Walks each dotted path in *template* to extract the value (and any
    nested tables), then creates the corresponding path in the user
    document.  Intermediate tables are created via ``tomlkit.table()``
    when missing.  Comments on the appended value's source position in
    the template are not propagated.  Only the value lands in the user
    file.
    """
    user_doc = tomlkit.parse(user_text)
    template_doc = tomlkit.parse(template_text)
    for dotted in missing_paths:
        segments = dotted.split(".")
        template_value = _walk_or_none(template_doc, segments)
        if template_value is None:
            continue
        _set_nested(
            user_doc, segments, template_value, table_factory=tomlkit.table,
        )
    return tomlkit.dumps(user_doc)


def _walk_or_none(doc: Any, segments: list[str]) -> Any:
    """Descend *segments* through *doc*, returning the final value or ``None``."""
    cursor = doc
    for segment in segments:
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor


def _set_nested(
    doc: Any,
    segments: list[str],
    value: Any,
    *,
    table_factory: Callable[[], Any],
) -> None:
    """Set ``doc[segments[0]][segments[1]]...[segments[-1]] = value``.

    Missing intermediate tables are created via *table_factory*:
    ``tomlkit.table`` for TOML round-trip preservation, plain ``dict``
    for YAML (ruamel auto-promotes plain dicts to ``CommentedMap`` on
    dump).  Existing intermediates that aren't mapping-shaped get
    replaced.
    """
    cursor = doc
    for segment in segments[:-1]:
        if segment not in cursor or not isinstance(cursor[segment], dict):
            cursor[segment] = table_factory()
        cursor = cursor[segment]
    cursor[segments[-1]] = value


def _append_missing_yaml(
    user_text: str,
    template_text: str,
    missing_paths: list[str],
) -> str:
    """YAML analog of :func:`_append_missing_toml`.

    Uses ruamel's round-trip parser so existing comments + key order
    survive the rewrite.
    """
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    user_data = yaml.load(user_text) or {}
    template_data = yaml.load(template_text) or {}
    for dotted in missing_paths:
        segments = dotted.split(".")
        template_value = _walk_or_none(template_data, segments)
        if template_value is None:
            continue
        _set_nested(user_data, segments, template_value, table_factory=dict)
    from io import StringIO  # noqa: PLC0415
    buffer = StringIO()
    yaml.dump(user_data, buffer)
    return buffer.getvalue()
