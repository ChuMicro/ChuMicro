"""Managed-block surgery for workspace.yml.

workspace.yml is user-owned, but a few of its top-level keys are
machine-managed: ``library_sources:`` by dev-mode setup, ``libraries:``
by the library subcommands.  Round-tripping the whole file through
ruamel drops the file's leading comment header when no key anchors it.
Ruamel attaches comments to keys, and a header with no following key
has nothing to hang on.  So each managed key is instead found and
replaced as a raw-text block via a single regex, leaving every other
byte (comments, blank lines, quoting, indentation) untouched.

A managed block is: an optional marker-comment line, the ``<key>:``
line, then every following indented line.  YAML block syntax means a
child at any nesting depth is just an indented line, so the same
finder works for a flat mapping (``library_sources:``) and a nested
one (``libraries:``).  The key's owner holds the full desired state
and rewrites the whole block; inline comments *inside* the block are
not preserved across rewrites.  That is the cost of not using a
comment-aware round-tripper.
"""

from __future__ import annotations

import re
from pathlib import Path


def _block_regex(key: str, marker: str) -> re.Pattern[str]:
    """Match a top-level ``key:`` block plus its indented children.

    ``(?m)^`` anchors at line starts so a ``key:`` reference inside a
    comment or nested under another key isn't caught.  The marker
    prefix is optional: with the marker (managed re-run) the match
    starts at the marker line. Without a marker (a bare ``key:``) it
    starts at the key line.  Either way the whole block is replaced
    atomically.
    """
    return re.compile(
        r"(?m)^"
        r"(?:\# " + re.escape(marker) + r"\n)?"
        + re.escape(key) + r":[ \t]*\n"
        r"(?:[ \t]+[^\n]*\n)*",
    )


def render_managed_block(key: str, marker: str, child_lines: list[str]) -> str:
    """Render full block text: marker comment + ``key:`` + children."""
    lines = [f"# {marker}", f"{key}:", *child_lines]
    return "\n".join(lines) + "\n"


def sync_managed_block(
    workspace_yaml: Path,
    key: str,
    marker: str,
    child_lines: list[str],
) -> bool:
    """Write or replace the managed *key* block in *workspace_yaml*.

    *child_lines* are the already-indented YAML lines that go under
    ``key:`` (no trailing newlines).  Returns ``True`` when the file
    was modified, ``False`` on an idempotent re-run.  Creates the
    file (and parents) when missing.  Every byte outside the managed
    block is preserved.
    """
    new_block = render_managed_block(key, marker, child_lines)
    existing_text = (
        workspace_yaml.read_text(encoding="utf-8")
        if workspace_yaml.is_file()
        else ""
    )

    match = _block_regex(key, marker).search(existing_text)
    if match is not None:
        if match.group(0) == new_block:
            return False
        new_text = (
            existing_text[: match.start()]
            + new_block
            + existing_text[match.end() :]
        )
    else:
        # No existing block: append. Add a blank-line separator from
        # prior content, but leave an empty file alone.
        prefix = existing_text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        new_text = prefix + new_block

    workspace_yaml.parent.mkdir(parents=True, exist_ok=True)
    workspace_yaml.write_text(new_text, encoding="utf-8")
    return True
