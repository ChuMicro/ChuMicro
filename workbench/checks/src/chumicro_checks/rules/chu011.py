"""CHU011 — plans-doc brevity.

Two sub-checks against ``plans/next-up.md``:

1. Every top-level ``- `` bullet contains at most five bullet markers
   (lead line plus indented sub-bullets within its extent).  Anything
   bigger should be promoted to a workstream file under
   ``plans/workstreams/`` (open) or ``plans/workstreams/archive/``
   (shipped) and replaced here by a one-line pointer.

2. The ``## Done (recent)`` section contains at most 25 entries.

A bullet's extent runs from its top-level ``- `` line until the next
top-level ``- ``, the next markdown heading, or end of file.

Suppression: ``<!-- noqa: CHU011 -->`` somewhere inside the offending
bullet's extent for the bullet-cap; anywhere in the file for the
Done-section cap.

Self-scope: the rule walks ``<repo_root>/plans/next-up.md``.  If
that file doesn't exist (a downstream workspace, the
workspace-template repo), the rule returns no findings — silent
no-op rather than error.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU011"
_BULLET_CAP = 5
_DONE_SECTION_CAP = 25
_DONE_HEADING_PREFIX = "Done"
_NOQA_TAG = "<!-- " + "noqa: " + _RULE_CODE + " -->"


def _is_top_level_bullet(line: str) -> bool:
    return line.startswith("- ")


def _is_any_bullet(line: str) -> bool:
    return line.lstrip(" \t").startswith("- ")


def _is_heading(line: str) -> bool:
    return line.startswith("#")


def _heading_text(line: str) -> str:
    return line.lstrip("#").lstrip(" ").rstrip()


def _find_bullet_extents(lines: list[str]) -> list[tuple[int, int]]:
    """Return ``[(start, end_exclusive)]`` for each top-level bullet."""
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
    return sum(1 for line in lines[start:end] if _is_any_bullet(line))


def _slice_has_noqa(lines: list[str], start: int, end: int) -> bool:
    return any(_NOQA_TAG in line for line in lines[start:end])


def _find_done_section_top_level_bullets(lines: list[str]) -> list[int]:
    """Return line indices of top-level bullets inside ``## Done ...``."""
    bullets: list[int] = []
    in_done = False
    for index, line in enumerate(lines):
        if _is_heading(line):
            in_done = _heading_text(line).startswith(_DONE_HEADING_PREFIX)
            continue
        if in_done and _is_top_level_bullet(line):
            bullets.append(index)
    return bullets


def _check_bullets(filepath: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for start, end in _find_bullet_extents(lines):
        if _slice_has_noqa(lines, start, end):
            continue
        marker_count = _count_bullet_markers(lines, start, end)
        if marker_count > _BULLET_CAP:
            findings.append(
                Finding(
                    path=filepath,
                    line=start + 1,
                    code=_RULE_CODE,
                    message=(
                        f"top-level bullet has {marker_count} bullet markers "
                        f"(cap {_BULLET_CAP}).  Promote detail to a workstream "
                        f"under plans/workstreams/ (open) or "
                        f"plans/workstreams/archive/ (shipped) and replace "
                        f"this entry with a one-line pointer.  Suppress with "
                        f"'{_NOQA_TAG}' if genuinely needed."
                    ),
                )
            )
    return findings


def _check_done_section_cap(filepath: Path, lines: list[str]) -> list[Finding]:
    if any(_NOQA_TAG in line for line in lines):
        return []
    bullets = _find_done_section_top_level_bullets(lines)
    if len(bullets) <= _DONE_SECTION_CAP:
        return []
    return [
        Finding(
            path=filepath,
            line=bullets[_DONE_SECTION_CAP] + 1,
            code=_RULE_CODE,
            message=(
                f"`## Done` section has {len(bullets)} entries "
                f"(cap {_DONE_SECTION_CAP}).  Drop the oldest entries — "
                f"commit messages and workstreams/archive/ keep the "
                f"durable record."
            ),
        )
    ]


class CHU011_PlansBrevity(Rule):
    code = _RULE_CODE
    description = (
        "plans/next-up.md bullet caps (5 markers per top-level bullet, "
        "25 entries in `## Done (recent)`)"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        target = repo_root / "plans" / "next-up.md"
        if not target.exists():
            return []
        lines = target.read_text(encoding="utf-8").splitlines()
        findings = list(_check_bullets(target, lines))
        findings.extend(_check_done_section_cap(target, lines))
        return findings


CHU011 = CHU011_PlansBrevity()
