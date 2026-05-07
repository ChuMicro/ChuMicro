"""Lint for plans-doc brevity.

CHU011 — ``plans/next-up.md`` is the agent-managed single source of
truth for the work queue.  Two checks:

1. Every top-level bullet contains at most 5 bullet markers (the lead
   ``- `` line plus any indented sub-bullets within its extent).
   Anything bigger should be promoted to a workstream file under
   ``plans/workstreams/`` (open work) or ``plans/workstreams/archive/``
   (shipped) and replaced here by a one-line pointer.

2. The ``## Done (recent)`` section contains at most 25 entries.  The
   pointer log is meant to age out — drop the oldest when adding a
   new one.  Commit messages, ``plans/history.md`` (dated entries),
   and ``plans/workstreams/archive/`` keep the durable record.

A bullet's "extent" runs from its top-level ``- `` line until the next
top-level ``- ``, the next heading line (``# ...`` / ``## ...`` /
etc.), or end of file.  Sub-bullets, paragraphs, and blockquotes
inside the extent all belong to the bullet.

Suppression: ``<!-- noqa: CHU011 -->`` somewhere inside the bullet's
extent (per-bullet), or anywhere in the file for the Done-section
cap.  Use sparingly — most violations want a workstream file or a
prune, not a noqa tag.

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
_BULLET_CAP = 5
_DONE_SECTION_CAP = 25

_DEFAULT_TARGETS = ("plans/next-up.md",)

#: Heading text (after the leading ``## ``) that marks the start of
#: the recent-Done log.  Match the prefix so a renamed heading like
#: ``## Done (recent — last 7 days)`` still works.
_DONE_HEADING_PREFIX = "Done"

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


def _heading_text(line: str) -> str:
    """Return the heading text (after the leading ``#``s and space)."""
    return line.lstrip("#").lstrip(" ").rstrip()


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


def _find_done_section_top_level_bullets(lines: list[str]) -> list[int]:
    """Return start-line indices of top-level bullets inside ``## Done ...``.

    The section starts at the first ``##`` heading whose text begins
    with ``Done`` and ends at the next heading at the same or higher
    level, or end of file.
    """
    bullets: list[int] = []
    in_done = False
    for index, line in enumerate(lines):
        if _is_heading(line):
            in_done = _heading_text(line).startswith(_DONE_HEADING_PREFIX)
            continue
        if in_done and _is_top_level_bullet(line):
            bullets.append(index)
    return bullets


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


def _check_done_section_cap(filepath: Path, lines: list[str]) -> list[str]:
    """Flag a Done section that grew past ``_DONE_SECTION_CAP`` entries.

    The cap is mechanical age-out — git log + workstream archives keep
    the durable record so the queue file doesn't accrete an ever-
    longer changelog.
    """
    if any(_NOQA_TAG in line for line in lines):
        return []
    bullets = _find_done_section_top_level_bullets(lines)
    if len(bullets) <= _DONE_SECTION_CAP:
        return []
    relative = (
        filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    )
    return [
        f"{relative}:{bullets[_DONE_SECTION_CAP] + 1}: {_CHU011} `## Done` "
        f"section has {len(bullets)} entries (cap {_DONE_SECTION_CAP}).  "
        f"Drop the oldest entries — commit messages, history.md, and "
        f"workstreams/archive/ keep the durable record.",
    ]


def check_file(filepath: Path) -> list[str]:
    """Run every CHU011 check that applies to *filepath*.

    Args:
        filepath: A markdown file to check.  Files that don't exist
            return an empty list.
    """
    if not filepath.exists():
        return []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    errors: list[str] = list(_check_bullets(filepath, lines))
    if filepath.name == "next-up.md":
        errors.extend(_check_done_section_cap(filepath, lines))
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Paths to check.  Defaults to ``plans/next-up.md`` under
            the repo root.
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
            f"plans/next-up.md is the agent-managed work-queue file; "
            f"bullets that grow paragraphs in place or Done logs that "
            f"never age out defeat the brevity contract.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
