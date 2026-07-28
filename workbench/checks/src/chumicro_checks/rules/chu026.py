"""CHU026: no orphan governance-doc files.

A governance document (``AGENTS.notes.md``, ``RULES.md``,
``*GUIDELINES*.md``) referenced from ``AGENTS.md`` must also be auto-
loaded via ``CLAUDE.md``'s ``@``-include chain.  Otherwise the file
exists on disk and ``AGENTS.md`` directs agents at it, but no agent
session ever opens it. The second-not-auto-loaded governance file
shape the AGENTS.md self-editing meta-rule forbids.

The rule walks ``CLAUDE.md``'s ``@<path>`` directives transitively to
build the set of auto-loaded files, then for each governance-doc-shaped
filename mentioned in any auto-loaded file checks:

* Does a file with that name exist in the repo root?
* Is it reachable from the ``@``-include closure?

A reference whose target file doesn't exist is not this rule's
concern (a CHU006-class leak).  A reference whose target exists and is
auto-loaded is fine.  A reference whose target exists but is NOT
auto-loaded is the orphan shape this rule catches.

Scope: ``CLAUDE.md`` at the repo root.  Absent, a silent no-op.

Suppression: ``<!-- noqa: CHU026 -->`` in ``AGENTS.md`` on the line
that names the governance file, paired with the one-line *why*.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU026"

_AT_INCLUDE = re.compile(r"^\s*@([A-Za-z0-9_./-]+\.md)\b", re.MULTILINE)

#: Governance-doc filename shapes: closed set of "second governance
#: file" patterns the no-orphan rule catches.
_GOVERNANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAGENTS\.notes\.md\b"),
    re.compile(r"\bRULES\.md\b"),
    re.compile(r"\b[A-Za-z0-9_-]*GUIDELINES[A-Za-z0-9_-]*\.md\b"),
)


def _resolve_includes(repo_root: Path, claude_md: Path) -> set[Path]:
    """Walk ``CLAUDE.md``'s ``@``-includes transitively.

    Returns the set of files reachable from ``CLAUDE.md`` via the
    ``@<path>`` directive at the start of a line.  Cycles are bounded
    by tracking visited files.
    """
    visited: set[Path] = {claude_md.resolve()}
    queue: list[Path] = [claude_md]
    while queue:
        current = queue.pop()
        try:
            text = current.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _AT_INCLUDE.finditer(text):
            included = (current.parent / match.group(1)).resolve()
            if not included.is_file():
                continue
            if included in visited:
                continue
            visited.add(included)
            queue.append(included)
    return visited


def _governance_refs(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, governance_filename)`` for each match."""
    hits: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_suppresses(line, _RULE_CODE):
            continue
        for pattern in _GOVERNANCE_PATTERNS:
            for match in pattern.finditer(line):
                hits.append((line_number, match.group(0)))
    return hits


class CHU026_OrphanGovernanceDoc(Rule):
    code = _RULE_CODE
    description = (
        "governance docs referenced from AGENTS.md must be auto-loaded "
        "via CLAUDE.md's @-include chain"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        claude_md = repo_root / "CLAUDE.md"
        if not claude_md.is_file():
            return []
        reachable = _resolve_includes(repo_root, claude_md)
        reachable_names = {path.name for path in reachable}

        findings: list[Finding] = []
        for included in reachable:
            try:
                text = included.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, filename in _governance_refs(text):
                target = repo_root / filename
                if not target.is_file():
                    # Reference to a non-existent file, out of scope
                    # (CHU006-class leak, not the orphan shape).
                    continue
                if filename in reachable_names:
                    continue
                findings.append(
                    Finding(
                        path=included,
                        line=line_number,
                        code=_RULE_CODE,
                        message=(
                            f"governance doc `{filename}` exists and is "
                            f"referenced here, but is not reachable from "
                            f"CLAUDE.md's @-include chain, so agents never "
                            f"auto-load it.  Either remove the file, drop "
                            f"the reference, or add `@{filename}` to "
                            f"CLAUDE.md."
                        ),
                    )
                )
        return findings


CHU026 = CHU026_OrphanGovernanceDoc()
