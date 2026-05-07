"""Lint for plans-doc brevity.

CHU011 — ``plans/next-up.md`` and ``plans/now.md`` are agent-managed
files with a brevity contract.  Two checks:

1. Every top-level bullet in either file contains at most 5 bullet
   markers (the lead ``- `` line plus any indented sub-bullets within
   its extent).  Anything bigger should be promoted to a workstream
   file under ``plans/workstreams/`` (open work) or
   ``plans/workstreams/archive/`` (shipped) and replaced here by a
   one-line pointer.

2. ``plans/now.md`` totals at most 25 lines.  The file is overwritten
   each ``task-checkpoint`` as a 30-second snapshot; longer drifts the
   file from its contract.

A bullet's "extent" runs from its top-level ``- `` line until the next
top-level ``- ``, the next heading line (``# ...`` / ``## ...`` / etc.),
or end of file.  Sub-bullets, paragraphs, and blockquotes inside the
extent all belong to the bullet.

Suppression: ``<!-- noqa: CHU011 -->`` somewhere inside the bullet's
extent (per-bullet), or anywhere in ``now.md`` for the file-line cap.
Use sparingly — most violations want a workstream file, not a noqa
tag.

Usage::

    python scripts/check_plans_brevity.py
    python scripts/check_plans_brevity.py [paths...]
    python scripts/run.py lint            # runs automatically
"""

from __future__ import annotations

import sys
from pathlib import Path

from repo_layout import ROOT

_CHU011 = "CHU011"
_NOW_LINE_CAP = 25
_BULLET_CAP = 5

_DEFAULT_TARGETS = (
    "plans/next-up.md",
    "plans/now.md",
)

# Constructed dynamically so ruff doesn't interpret a literal ``noqa``
# inside this source file as a directive of its own.
_NOQA_TAG = "<!-- " + "noqa: " + _CHU011 + " -->"


def _is_heading(line: str) -> bool:
    """Return whether *line* starts a markdown heading."""
    return line.startswith("#")


def _is_top_level_bullet(line: str) -> bool:
    """Return whether *line* is a column-zero ``- `` bullet."""
    return line.startswith("- ")


def _is_any_bullet(line: str) -> bool:
    """Return whether *line* is any markdown list bullet (top-level or sub)."""
    return line.lstrip(" \t").startswith("- ")


def _find_bullet_extents(lines: list[str]) -> list[tuple[int, int]]:
    """Return ``[(start, end_exclusive)]`` for each top-level bullet.

    A bullet's extent runs from its ``- `` line until either the next
    top-level ``- `` line, the next heading line, or end of file.
    """
    extents: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if _is_top_level_bullet(line):
            if start is not None:
                extents.append((start, index))
            start = index
        elif _is_heading(line) and start is not None:
            extents.append((start, index))
            start = None
    if start is not None:
        extents.append((start, len(lines)))
    return extents


def _count_bullet_markers(lines: list[str], start: int, end: int) -> int:
    """Return the number of bullet-shaped lines within ``lines[start:end]``."""
    return sum(1 for line in lines[start:end] if _is_any_bullet(line))


def _has_noqa(lines: list[str], start: int, end: int) -> bool:
    """Return whether the slice contains a CHU011 suppression marker."""
    return any(_NOQA_TAG in line for line in lines[start:end])


def _check_bullets(filepath: Path, lines: list[str]) -> list[str]:
    """Flag every top-level bullet whose extent has more than five markers.

    Args:
        filepath: Source file (used for error-message paths).
        lines: File contents already split on newlines.
    """
    relative = (
        filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    )
    errors: list[str] = []
    for start, end in _find_bullet_extents(lines):
        if _has_noqa(lines, start, end):
            continue
        marker_count = _count_bullet_markers(lines, start, end)
        if marker_count > _BULLET_CAP:
            errors.append(
                f"{relative}:{start + 1}: {_CHU011} top-level bullet has "
                f"{marker_count} bullet markers (cap {_BULLET_CAP}).  "
                f"Promote detail to a workstream under "
                f"plans/workstreams/ (open) or plans/workstreams/archive/ "
                f"(shipped) and replace this entry with a one-line pointer.  "
                f"Suppress with '{_NOQA_TAG}' if genuinely needed.",
            )
    return errors


def _check_now_md_cap(filepath: Path, lines: list[str]) -> list[str]:
    """Flag ``plans/now.md`` if it grows past the line cap.

    Args:
        filepath: Source file (used for error-message paths).
        lines: File contents already split on newlines.
    """
    if any(_NOQA_TAG in line for line in lines):
        return []
    if len(lines) <= _NOW_LINE_CAP:
        return []
    relative = (
        filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    )
    return [
        f"{relative}:1: {_CHU011} file has {len(lines)} lines (cap "
        f"{_NOW_LINE_CAP}).  now.md is a 30-second snapshot, overwritten "
        f"each task-checkpoint — compress further or push detail into "
        f"next-up.md / a workstream.",
    ]


def check_file(filepath: Path) -> list[str]:
    """Run every CHU011 check that applies to *filepath*.

    Args:
        filepath: A markdown file to check.  Files that don't exist or
            aren't recognized targets return an empty list.
    """
    if not filepath.exists():
        return []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    errors: list[str] = list(_check_bullets(filepath, lines))
    if filepath.name == "now.md":
        errors.extend(_check_now_md_cap(filepath, lines))
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Paths to check.  Defaults to ``plans/next-up.md`` and
            ``plans/now.md`` under the repo root.
    """
    if argv:
        targets = [Path(arg) for arg in argv]
    else:
        targets = [ROOT / target for target in _DEFAULT_TARGETS]
    all_errors: list[str] = []
    for path in targets:
        if path.is_dir():
            for candidate in sorted(path.rglob("*.md")):
                all_errors.extend(check_file(candidate))
        else:
            all_errors.extend(check_file(path))
    if all_errors:
        for error in all_errors:
            print(error)
        print(
            f"\nFound {len(all_errors)} {_CHU011} violation(s) in plans/.  "
            f"These files are agent-managed; bullets that grow paragraphs "
            f"in place defeat the brevity contract.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
