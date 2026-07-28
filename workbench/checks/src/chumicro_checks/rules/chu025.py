"""CHU025: ``Superseded by:`` pointer integrity.

CHU019 already enforces that an ADR's status, filename marker, and
``Superseded by:`` line agree.  This rule fills the remaining gaps:

- A ``Superseded by: [Decision NNNN]`` line whose cited NNNN has no
  matching file in ``plans/decisions/`` (a dangling pointer: the
  target was renamed or removed without fixing the inbound link).
- A filename ``NNNN-SUPERSEDED-BY-MMMM-<slug>.md`` whose target MMMM
  has no matching file (same shape via the filename marker).
- An ADR with ``Status: accepted`` that also carries a ``Superseded by:``
  line, a half-finished supersession edit. Either the status should
  flip or the field should not be there.

The check is glob-based existence ("is there any file whose stem starts
with ``MMMM-``?"), which works under the dead-record filename
convention without coupling to slug knowledge.

Scope: ``plans/decisions/*.md``.  Absent, a silent no-op.

Suppression: ``<!-- noqa: CHU025 -->`` anywhere in the offending file.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU025"
_NOQA_TAG = "<!-- " + "noqa: " + _RULE_CODE + " -->"

_STATUS = re.compile(r"^Status:\s*`?(\w+)`?", re.MULTILINE)
_SUPERSEDED_BY_LINE = re.compile(r"^Superseded by:.*$", re.MULTILINE)
_NNNN_CITE = re.compile(r"\b(?:Decision|ADR)\s+(\d{4})\b")
_FILENAME_MARKER = re.compile(r"^\d{4}-SUPERSEDED-BY-(\d{4})-")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _target_exists(decisions_dir: Path, number: str) -> bool:
    """True when any ADR file under *decisions_dir* starts with ``number-``."""
    return any(decisions_dir.glob(f"{number}-*.md"))


def _check_file(
    filepath: Path, decisions_dir: Path,
) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if _NOQA_TAG in text:
        return []

    status_match = _STATUS.search(text)
    if status_match is None:
        return []
    status = status_match.group(1).lower()

    findings: list[Finding] = []

    def flag(line: int, message: str) -> None:
        findings.append(
            Finding(path=filepath, line=line, code=_RULE_CODE, message=message),
        )

    superseded_line = _SUPERSEDED_BY_LINE.search(text)

    # Half-finished supersession: accepted + Superseded-by line.
    if status == "accepted" and superseded_line is not None:
        flag(
            _line_of(text, superseded_line.start()),
            "ADR has `Status: accepted` but also a `Superseded by:` line; "
            "flip the status to `superseded` or remove the field",
        )

    # Dangling Superseded-by cite.
    if superseded_line is not None:
        cite = _NNNN_CITE.search(superseded_line.group(0))
        if cite is not None and not _target_exists(decisions_dir, cite.group(1)):
            flag(
                _line_of(text, superseded_line.start()),
                f"`Superseded by:` cites Decision {cite.group(1)} but no "
                f"`{cite.group(1)}-*.md` file exists in plans/decisions/",
            )

    # Dangling filename marker.
    filename_marker = _FILENAME_MARKER.match(filepath.stem)
    if filename_marker is not None:
        target = filename_marker.group(1)
        if not _target_exists(decisions_dir, target):
            flag(
                1,
                f"filename marks SUPERSEDED-BY-{target} but no "
                f"`{target}-*.md` file exists in plans/decisions/",
            )

    return findings


class CHU025_SupersededPointerIntegrity(Rule):
    code = _RULE_CODE
    description = (
        "`Superseded by:` pointers + filename markers must name an "
        "existing ADR; an `accepted` ADR cannot carry the field"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        decisions = repo_root / "plans" / "decisions"
        if not decisions.is_dir():
            return []
        findings: list[Finding] = []
        for filepath in sorted(decisions.glob("*.md")):
            if filepath.name == "README.md":
                continue
            findings.extend(_check_file(filepath, decisions))
        return findings


CHU025 = CHU025_SupersededPointerIntegrity()
