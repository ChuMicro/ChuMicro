"""CHU028: cross-ADR principle duplication.

Regression guard for the partial-supersession bloat pattern where a
corrected principle ends up stated in full in *both* an older ADR's
edited section AND the newer ADR that supersedes it. When an in-place
supersession edits only the older record, the newer one restates the
same principle, and the reader hits the same paragraph twice across
two files.

Engine A applied to markdown paragraphs across
``plans/decisions/*.md`` (excluding ``README.md``):

* Extract each ADR's non-scaffolding paragraphs (split on blank
  lines. Markdown headers, ``Status: / Date: / Related: /
  Superseded by: / Archived:`` lines, and blockquote lines are
  treated as boundaries, not content).  A fenced code block bounds a
  paragraph and its contents are excluded entirely: a canonical config
  or command snippet shared verbatim across two ADRs is legitimate, not
  a duplicated principle.
* Normalize to a tuple of lowercased alphanumeric word tokens
  (matching CHU027's normalizer so the engine has consistent shape).
* Hash paragraphs at or above the minimum-token floor, then flag
  fingerprints that span ≥2 ADR files (the partial-supersession
  shape: one invariant, one home).

Floor is set to 20 tokens, higher than CHU027's 12, because ADR
prose runs longer and short paragraphs share idiomatic ADR phrasing
("This ADR doesn't pre-emptively edit X" / "Out of scope") without
being principle-level duplication.

Scope: ``plans/decisions/*.md``.  Absent, a silent no-op.

Suppression: ``<!-- noqa: CHU028 -->`` on the first line of the
duplicated paragraph, paired with the one-line *why* AGENTS.md
requires.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU028"

_MIN_TOKENS = 20

_TOKEN = re.compile(r"\b[a-z][a-z0-9]+\b")

#: Line shapes that are not principle content: section scaffolding,
#: ADR metadata fields, blockquotes used for asides.
_SCAFFOLDING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*#"),                       # markdown headers
    re.compile(r"^\s*Status:\s*"),
    re.compile(r"^\s*Date:\s*"),
    re.compile(r"^\s*Related:\s*"),
    re.compile(r"^\s*Superseded by:\s*"),
    re.compile(r"^\s*Archived:\s*"),
    re.compile(r"^\s*>\s"),                     # blockquote lines
)

#: A fenced code-block delimiter line.  It bounds a paragraph and
#: toggles fenced state; the fence and every line between fences is code
#: or config, not principle prose, so none of it is hashed.
_FENCE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class _Paragraph:
    filepath: Path
    line: int
    tokens: tuple[str, ...]
    suppressed: bool


def _is_scaffolding(line: str) -> bool:
    return any(pattern.match(line) for pattern in _SCAFFOLDING_PATTERNS)


def _normalize(text: str) -> tuple[str, ...]:
    """Lowercase + alphanumeric word-token sequence."""
    return tuple(_TOKEN.findall(text.lower()))


def _extract_paragraphs(text: str, filepath: Path) -> list[_Paragraph]:
    """Yield one ``_Paragraph`` per non-scaffolding markdown paragraph.

    A paragraph is a run of consecutive non-blank, non-scaffolding
    lines.  Any blank line, header, or metadata field acts as a
    paragraph boundary.  A line carrying ``noqa: CHU028`` marks the
    enclosing paragraph as suppressed and does not contribute tokens.
    Adding a suppression marker affects only whether the finding
    is reported, never which paragraphs hash together.
    """
    paragraphs: list[_Paragraph] = []
    lines = text.splitlines()
    current_lines: list[str] = []
    current_start = 0
    suppressed = False
    in_fence = False

    def flush() -> None:
        nonlocal current_lines, current_start, suppressed
        if current_lines or suppressed:
            joined = " ".join(current_lines)
            paragraphs.append(_Paragraph(
                filepath=filepath,
                line=current_start,
                tokens=_normalize(joined),
                suppressed=suppressed,
            ))
        current_lines = []
        suppressed = False

    for line_no, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            # A fence delimiter bounds the current paragraph and flips
            # fenced state; neither it nor its contents are prose.
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            # Code / config sample inside a fence contributes no tokens,
            # so a snippet shared verbatim across ADRs is not a duplicate.
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if _is_scaffolding(line):
            flush()
            continue
        if line_suppresses(line, _RULE_CODE):
            suppressed = True
            if not current_lines:
                current_start = line_no
            continue
        if not current_lines:
            current_start = line_no
        current_lines.append(stripped)
    flush()
    return paragraphs


class CHU028_AdrPrincipleDuplication(Rule):
    code = _RULE_CODE
    description = (
        "no cross-ADR principle duplication: one invariant, one home"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        decisions = repo_root / "plans" / "decisions"
        if not decisions.is_dir():
            return []

        paragraphs: list[_Paragraph] = []
        for filepath in sorted(decisions.glob("*.md")):
            if filepath.name == "README.md":
                continue
            try:
                text = filepath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            paragraphs.extend(_extract_paragraphs(text, filepath))

        paragraphs = [
            paragraph for paragraph in paragraphs
            if len(paragraph.tokens) >= _MIN_TOKENS
        ]

        by_fingerprint: dict[tuple[str, ...], list[_Paragraph]] = defaultdict(list)
        for paragraph in paragraphs:
            by_fingerprint[paragraph.tokens].append(paragraph)

        findings: list[Finding] = []
        for group in by_fingerprint.values():
            files = {paragraph.filepath for paragraph in group}
            if len(files) < 2:
                continue
            sites = ", ".join(
                f"{paragraph.filepath.relative_to(repo_root)}:{paragraph.line}"
                for paragraph in group
            )
            for paragraph in group:
                if paragraph.suppressed:
                    continue
                findings.append(
                    Finding(
                        path=paragraph.filepath,
                        line=paragraph.line,
                        code=_RULE_CODE,
                        message=(
                            f"ADR principle duplicated across "
                            f"{len(files)} ADRs; state once and "
                            f"cross-link from the rest.  Sites: {sites}"
                        ),
                    )
                )
        return findings


CHU028 = CHU028_AdrPrincipleDuplication()
