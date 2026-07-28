"""CHU024: banned ADR-authoring section markers in ``plans/decisions/``.

The ADR README's "Edit the body in place" rule forbids history banners
on accepted decision records: ``Update`` heading banners at any heading
depth, dated or paren-less (``## Update (YYYY-MM-DD)``,
``### Update (…)``, ``## Update 2026-01-03``, ``## Updates``),
``## Amendments`` / ``## Changelog`` / ``## Progress notes`` sections,
``Amended by Decision NNNN`` blockquotes, and "this decision has been
revised" preambles.  An accepted ADR describes the *current* state of
the decision. Scope changes get an in-place body edit, not a banner.

The patterns are anchored to line-start (or blockquote-marker) so the
README and other ADRs that *name* the banned shapes in backtick-quoted
prose don't self-flag. The rule fires on actual headings and
blockquotes, not on the rule's own documentation.

Scope: ``plans/decisions/*.md``.  Absent, a silent no-op.

Suppression: ``<!-- noqa: CHU024 -->`` on the offending line, paired
with the one-line *why* AGENTS.md requires.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU024"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^\s*#{2,}\s+Updates?\b"),
        "ADR ``Update`` banner heading: edit the body in place instead",
    ),
    (
        re.compile(r"^\s*##\s+Amendments?\b"),
        "ADR ``## Amendments`` section: edit the body in place instead",
    ),
    (
        re.compile(r"^\s*##\s+Changelog\b", re.IGNORECASE),
        "ADR ``## Changelog`` section: git log on the ADR carries history",
    ),
    (
        re.compile(r"^\s*##\s+Progress\s+notes\b", re.IGNORECASE),
        "ADR ``## Progress notes`` section: status belongs in the workstream file",
    ),
    (
        re.compile(r"^\s*>.{0,80}\bAmended by\b"),
        "ADR ``Amended by`` blockquote: cross-link the successor inline instead",
    ),
    (
        re.compile(r"\bThis was revised\b"),
        "ADR revision narrative: describe current state, let git log carry history",
    ),
    (
        re.compile(r"\bthis decision has been revised\b", re.IGNORECASE),
        "ADR revision preamble: describe current state, let git log carry history",
    ),
    (
        re.compile(r"^\s*Revised:\s*\d{4}-\d{2}-\d{2}\b"),
        "ADR dated revision banner: edit the body in place; let git log carry history",
    ),
)


def _scan_root(repo_root: Path) -> Path | None:
    decisions = repo_root / "plans" / "decisions"
    return decisions if decisions.is_dir() else None


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_suppresses(line, _RULE_CODE):
            continue
        for pattern, message in _PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        path=filepath,
                        line=line_number,
                        code=_RULE_CODE,
                        message=message,
                    )
                )
                break
    return findings


class CHU024_AdrBanners(Rule):
    code = _RULE_CODE
    description = (
        "no history banners on accepted ADRs: edit the body in place"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        root = _scan_root(repo_root)
        if root is None:
            return []
        findings: list[Finding] = []
        for filepath in iter_text_files(root, suffixes=(".md",)):
            findings.extend(_check_file(filepath))
        return findings


CHU024 = CHU024_AdrBanners()
