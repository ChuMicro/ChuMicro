"""CHU032: no cross-reference pointer phrases in publishable comments.

The AGENTS.md "Code comments" non-negotiable requires every comment and
docstring to stand alone for a cold reader of its own file: no
"see ``module``'s docstring", no ":mod:`other` documents the rationale",
no "follows the pattern in X".  A reader who installed the package off
PyPI has the shipped source, not the sibling file the pointer names, so
the pointer leaves them stranded.  Rationale that outlives a commit
belongs in the relevant ADR or workstream file, not a cross-file
breadcrumb.

This rule mechanizes the closed set of pointer phrases that always
signal the drift.  It deliberately does NOT flag a bare dependency
mention (``Built on :mod:`chumicro_sockets```) or a fake naming the
real type it stands in for.  Those name an architectural fact, not a
"go read another file" instruction, and blanket-flagging them would
fire on hundreds of legitimate lines.  The judgment half (is this
comment self-contained?) stays with ``/audit-comments`` and reviewer;
this lint is the safety net for the enumerated phrases.

Flagged phrases:

- ``see ``X``'s docstring``: a possessive pointer at a named other
  thing's docstring.
- ``documents the rationale`` / ``documents the why``: a comment
  delegating its own reasoning to another location.
- ``follows the pattern in`` / ``follows the pattern of`` /
  ``per the pattern in``: a cross-reference to a pattern's home
  instead of stating what the code does.

Scope: ``libraries/*/src/`` and ``workbench/*/src/``.  ``tests/`` and
``docs/`` are out of scope.

Carve-out: a line carrying a ``# noqa`` directive is exempt.  A
suppression explanation legitimately names its duplicate's home (the
CHU027 sites point at the sibling that owns the canonical copy).

Self-scope: the rule resolves ``src`` directories under
``<repo_root>/libraries/`` and ``<repo_root>/workbench/``.  In a tree
without those (a downstream user workspace), it returns no findings, a
silent no-op.

Suppression: ``# noqa: CHU032`` on the offending line, paired with the
one-line *why* AGENTS.md requires.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import has_noqa
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU032"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # ``see ``Name``'s docstring`` is a pointer at a named other
        # thing's docstring.  The backtick-quoted name + possessive is
        # the signal; "see the module docstring" (no name) is a
        # same-file reference and stays clean.
        re.compile(r"see\s+``[^`]+``'s docstring", re.IGNORECASE),
        "'see ``X``'s docstring' pointer: restate the fact inline; a "
        "consumer who installed the package can't read a sibling file's "
        "docstring",
    ),
    (
        re.compile(r"documents the (?:rationale|why|reasoning)", re.IGNORECASE),
        "'documents the rationale' cross-reference: state the why here, "
        "or lift it to the relevant ADR / workstream file",
    ),
    (
        re.compile(
            r"(?:follows|per) the pattern (?:in|of)\b",
            re.IGNORECASE,
        ),
        "'follows the pattern in X' cross-reference: describe what this "
        "code does; a cold reader of this file can't follow the pointer",
    ),
)

#: The rule's own source and tests carry the flagged phrases as docstring
#: and fixture data; exempting them keeps the rule off its own
#: documentation.  Paths are repo-root-relative.
_SELF_EXEMPT_RELPATHS: frozenset[Path] = frozenset({
    Path("workbench/checks/src/chumicro_checks/rules/chu032.py"),
    Path("workbench/checks/tests/test_chu032.py"),
})


def _is_self_exempt(filepath: Path, repo_root: Path) -> bool:
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    return relative in _SELF_EXEMPT_RELPATHS


def _scan_roots(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    for parent in ("libraries", "workbench"):
        parent_dir = repo_root / parent
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            src_dir = package_dir / "src"
            if src_dir.is_dir():
                roots.append(src_dir)
    return roots


def _check_file(filepath: Path, repo_root: Path) -> list[Finding]:
    if _is_self_exempt(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        # Any noqa line is exempt: a suppression explanation legitimately
        # names its duplicate's home (the CHU027 sites point at the
        # sibling that owns the canonical copy).
        if has_noqa(line):
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


class CHU032_CrossReferencePointer(Rule):
    code = _RULE_CODE
    description = (
        "no cross-reference pointer phrases in publishable comments: "
        "comments stand alone for a cold reader of their own file"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_roots(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file(filepath, repo_root))
        return findings


CHU032 = CHU032_CrossReferencePointer()
