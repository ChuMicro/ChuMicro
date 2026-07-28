"""CHU011: plans-doc brevity.

Two sub-checks against ``plans/next-up.md``:

1. Every top-level ``- `` bullet contains at most ONE list marker
   (the lead line itself).  Sub-bullets are forbidden; counted markers
   include dash / star / plus bullets and ``1.`` / ``2)`` ordered
   items, so an ordered sub-list doesn't slip the cap.  Anything that
   needs structure should be promoted to a workstream file under
   ``plans/workstreams/`` (open) or ``plans/workstreams/archive/``
   (shipped) and replaced here by a one-line pointer.

2. No ``## Done`` heading (or ``## Done (recent)`` / similar).
   Recent landings live in ``git log``. The file tracks status only.

A bullet's extent runs from its top-level ``- `` line until the next
top-level ``- ``, the next markdown heading, or end of file.

Suppression: ``<!-- noqa: CHU011 -->`` somewhere inside the offending
bullet's extent for the bullet-cap; on the heading line itself for the
Done-section ban.

Self-scope: the rule walks ``<repo_root>/plans/next-up.md``.  If
that file doesn't exist (a downstream workspace, the
workspace-template repo), the rule returns no findings, a silent
no-op rather than error.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU011"
_BULLET_CAP = 1
_DONE_HEADING_PREFIX = "Done"
_NOQA_TAG = "<!-- " + "noqa: " + _RULE_CODE + " -->"

#: Any list marker counted toward a bullet's cap: dash / star / plus
#: unordered bullets and ``1.`` / ``2)`` ordered items.  An ordered
#: sub-list is the same "needs structure → promote it" shape a dash
#: sub-bullet is, so it counts too.
_ANY_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _is_top_level_bullet(line: str) -> bool:
    return line.startswith("- ")


def _is_any_bullet(line: str) -> bool:
    return _ANY_BULLET.match(line) is not None


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


def _find_done_heading_indices(lines: list[str]) -> list[int]:
    """Return line indices of ``## Done…`` headings."""
    indices: list[int] = []
    for index, line in enumerate(lines):
        if _is_heading(line) and _heading_text(line).startswith(_DONE_HEADING_PREFIX):
            indices.append(index)
    return indices


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
                        f"(cap {_BULLET_CAP}: one bullet per item, no "
                        f"sub-bullets).  Promote detail to a workstream under "
                        f"plans/workstreams/ (open) or "
                        f"plans/workstreams/archive/ (shipped) and replace this "
                        f"entry with a one-line pointer.  Suppress with "
                        f"'{_NOQA_TAG}' if genuinely needed."
                    ),
                )
            )
    return findings


def _check_done_heading_absent(filepath: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for index in _find_done_heading_indices(lines):
        if _NOQA_TAG in lines[index]:
            continue
        findings.append(
            Finding(
                path=filepath,
                line=index + 1,
                code=_RULE_CODE,
                message=(
                    f"`## Done` heading is not allowed; next-up.md tracks "
                    f"status only.  Recent landings live in `git log`; longer "
                    f"detail in plans/workstreams/archive/.  Suppress with "
                    f"'{_NOQA_TAG}' on the heading line if genuinely needed."
                ),
            )
        )
    return findings


class CHU011_PlansBrevity(Rule):
    code = _RULE_CODE
    description = (
        "plans/next-up.md is status only: one bullet per item, no "
        "sub-bullets, no `## Done` section"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        target = repo_root / "plans" / "next-up.md"
        if not target.exists():
            return []
        lines = target.read_text(encoding="utf-8").splitlines()
        findings = list(_check_bullets(target, lines))
        findings.extend(_check_done_heading_absent(target, lines))
        return findings


CHU011 = CHU011_PlansBrevity()
