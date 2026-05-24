"""CHU029: every ADR carries a non-empty ``Summary:`` frontmatter field.

The SessionStart hook surfaces each ADR's ``Summary:`` line so an
agent landing in a session sees what was decided, not just the
filename slug.  A missing or empty field silently hollows out that
surface: the hook prints the slug followed by a dash and nothing
else.  This rule enforces the contract so it doesn't depend on
review discipline.

For every ``plans/decisions/NNNN*.md`` (``README.md`` excluded):

- a ``Summary:`` line must exist in the first 10 lines (the
  frontmatter window every ADR's header fits within).
- the value after ``Summary:`` must be non-empty.
- the value must not exceed 200 characters.  The hook output is
  budgeted at ~10 KB across 77 active ADRs at that cap; a runaway
  Summary blows the budget the workstream sized for.

Self-scope: ``<repo_root>/plans/decisions``.  Absent (a downstream
workspace, the workspace-template), no findings, a silent no-op.

Suppression: ``<!-- noqa: CHU029 -->`` anywhere in the offending file.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU029"
_NOQA_TAG = "<!-- " + "noqa: " + _RULE_CODE + " -->"

_PREFIX = re.compile(r"^\d{4}-")
_SUMMARY = re.compile(r"^Summary:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_MAX_CHARS = 200
_FRONTMATTER_LINES = 10


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if _NOQA_TAG in text:
        return []

    head = "\n".join(text.splitlines()[:_FRONTMATTER_LINES])
    match = _SUMMARY.search(head)
    if match is None:
        return [
            Finding(
                path=filepath,
                line=1,
                code=_RULE_CODE,
                message=(
                    f"missing `Summary:` frontmatter field in the first "
                    f"{_FRONTMATTER_LINES} lines: add a one-sentence "
                    f"machine-extractable summary between `Date:` and "
                    f"`Related:`"
                ),
            )
        ]

    value = match.group(1)
    line = text.count("\n", 0, match.start()) + 1

    if not value:
        return [
            Finding(
                path=filepath,
                line=line,
                code=_RULE_CODE,
                message="`Summary:` field is empty: name what was decided",
            )
        ]

    if len(value) > _MAX_CHARS:
        return [
            Finding(
                path=filepath,
                line=line,
                code=_RULE_CODE,
                message=(
                    f"`Summary:` is {len(value)} chars (cap {_MAX_CHARS}): "
                    f"trim it"
                ),
            )
        ]

    return []


class CHU029_AdrSummaryField(Rule):
    code = _RULE_CODE
    description = (
        f"every ADR must carry a non-empty `Summary:` frontmatter field "
        f"(<= {_MAX_CHARS} chars) in the first {_FRONTMATTER_LINES} lines"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        decisions = repo_root / "plans" / "decisions"
        if not decisions.is_dir():
            return []
        findings: list[Finding] = []
        for filepath in sorted(decisions.glob("*.md")):
            if filepath.name == "README.md":
                continue
            if not _PREFIX.match(filepath.stem):
                continue
            findings.extend(_check_file(filepath))
        return findings


CHU029 = CHU029_AdrSummaryField()
