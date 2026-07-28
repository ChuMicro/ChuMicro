"""CHU019: archived-decision marker consistency.

Session start scans the decision-record directory by ``ls``. The
filename is the index.  A dead decision must announce that in its
filename so the reader skips it without opening it.  The status
field, the filename marker, and the ``Archived:`` field each carry
one bit of the same fact. If they disagree a future reader is misled
exactly where the convention was meant to help.  Prose discipline
doesn't catch that. This rule does, since a lintable contract must be
mechanized rather than left to doc review.

For every ``plans/decisions/NNNN*.md`` (``README.md`` excluded):

- ``Status: superseded`` ⟺ filename ``NNNN-SUPERSEDED-BY-MMMM-<slug>``,
  and a ``Superseded by:`` line exists that cites ``MMMM``.
- filename ``NNNN-INERT-<slug>`` ⟺ an ``Archived:`` header field,
  with ``Status:`` left ``accepted`` (archiving is not a status).
- no two records share a four-digit number prefix (a botched rename).

The two markers are mutually exclusive: each anchors its token right
after the ``NNNN-`` prefix, so "both at once" is unreachable rather
than a checked rule.

Number *gaps* are not flagged. An intentionally skipped number is
allowed.

Self-scope: ``<repo_root>/plans/decisions``.  Absent (a downstream
workspace, the workspace-template), no findings, a silent no-op.

Suppression: ``<!-- noqa: CHU019 -->`` anywhere in the offending file.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU019"
_NOQA_TAG = "<!-- " + "noqa: " + _RULE_CODE + " -->"

_PREFIX = re.compile(r"^(\d{4})-")
_SUPERSEDED_MARKER = re.compile(r"^\d{4}-SUPERSEDED-BY-(\d{4})-")
_INERT_MARKER = re.compile(r"^\d{4}-INERT-")
_STATUS = re.compile(r"^Status:\s*`?(\w+)`?", re.MULTILINE)
_SUPERSEDED_BY = re.compile(r"^Superseded by:.*$", re.MULTILINE)
_ARCHIVED = re.compile(r"^Archived:.*$", re.MULTILINE)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if _NOQA_TAG in text:
        return []

    stem = filepath.stem
    status_match = _STATUS.search(text)
    if status_match is None:
        # A numbered record (or one carrying a lifecycle marker) whose
        # ``Status:`` line is missing or styled so the parser can't read
        # it (``**Status:**``, indented) is exactly the malformed record
        # most in need of flagging: the filename asserts a lifecycle the
        # body can't confirm.  A non-numbered ``.md`` is genuinely not a
        # decision record and stays a silent no-op.
        if (
            _PREFIX.match(stem) is not None
            or _SUPERSEDED_MARKER.match(stem) is not None
            or _INERT_MARKER.match(stem) is not None
        ):
            return [
                Finding(
                    path=filepath,
                    line=1,
                    code=_RULE_CODE,
                    message=(
                        "decision record has no parseable `Status:` line; "
                        "the filename asserts a lifecycle the body can't "
                        "confirm; add a `Status:` field at line start "
                        "(e.g. `Status: accepted`)"
                    ),
                )
            ]
        return []
    status = status_match.group(1).lower()
    status_line = _line_of(text, status_match.start())

    superseded_marker = _SUPERSEDED_MARKER.match(stem)
    inert_marker = _INERT_MARKER.match(stem)
    superseded_by = _SUPERSEDED_BY.search(text)
    archived = _ARCHIVED.search(text)

    findings: list[Finding] = []

    def flag(line: int, message: str) -> None:
        findings.append(
            Finding(
                path=filepath, line=line, code=_RULE_CODE, message=message,
            )
        )

    # A filename cannot carry both markers: each regex anchors the
    # token immediately after the `NNNN-` prefix, so they are mutually
    # exclusive: no "both" check is reachable.

    if status == "superseded" and superseded_marker is None:
        flag(status_line, "Status is `superseded` but the filename lacks "
                          "the `-SUPERSEDED-BY-NNNN-` marker; rename it so "
                          "the index reader skips it without opening it")
    if superseded_marker and status != "superseded":
        flag(status_line, f"filename marks SUPERSEDED-BY but Status is "
                          f"`{status}` (must be `superseded`)")
    if status == "superseded" and superseded_by is None:
        flag(status_line, "Status is `superseded` but there is no "
                          "`Superseded by:` line naming the successor")
    if superseded_marker and superseded_by is not None:
        successor = superseded_marker.group(1)
        if successor not in superseded_by.group(0):
            flag(_line_of(text, superseded_by.start()),
                 f"filename marks successor {successor} but the "
                 f"`Superseded by:` line cites a different record")

    if inert_marker and archived is None:
        flag(1, "filename marks INERT but there is no `Archived:` header "
                "field stating why it is inert")
    if inert_marker and status != "accepted":
        flag(status_line, f"INERT records keep `Status: accepted` "
                          f"(archiving is not a status); found `{status}`")
    if archived is not None and inert_marker is None:
        flag(_line_of(text, archived.start()),
             "`Archived:` field present but the filename lacks the "
             "`-INERT-` marker; rename it")

    return findings


class CHU019_ArchivedDecisionMarkers(Rule):
    code = _RULE_CODE
    description = (
        "dead decision records must carry a filename lifecycle marker "
        "matching their status / Archived field"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        decisions = repo_root / "plans" / "decisions"
        if not decisions.is_dir():
            return []

        findings: list[Finding] = []
        prefixes: dict[str, list[Path]] = {}
        for filepath in sorted(decisions.glob("*.md")):
            if filepath.name == "README.md":
                continue
            prefix_match = _PREFIX.match(filepath.stem)
            if prefix_match is not None:
                prefixes.setdefault(prefix_match.group(1), []).append(
                    filepath
                )
            findings.extend(_check_file(filepath))

        for number, paths in sorted(prefixes.items()):
            if len(paths) > 1:
                collision = ", ".join(entry.name for entry in paths)
                for path in paths:
                    findings.append(
                        Finding(
                            path=path,
                            line=1,
                            code=_RULE_CODE,
                            message=(
                                f"number {number} is used by "
                                f"{len(paths)} files ({collision}); a "
                                f"rename must keep the number unique"
                            ),
                        )
                    )
        return findings


CHU019 = CHU019_ArchivedDecisionMarkers()
