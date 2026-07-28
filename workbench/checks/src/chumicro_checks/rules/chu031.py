"""CHU031: noqa / pragma explanation separator must be `` - `` (space hyphen space).

A ``# noqa: CODE`` or ``# pragma: no cover`` comment that carries a
trailing explanation joins the suppression to the explanation with
``" - "`` (space hyphen space).  Em-dash (``" — "``), en-dash
(``" – "``), and double-hyphen (``" -- "``) separators are the drift
class this rule flags: one convention across the publishable trees
keeps the suppression comments grep-able and reads the same in every
package.

What the rule flags:

- ``# noqa: ARG002 — runner contract`` (em-dash)
- ``# pragma: no cover – defensive`` (en-dash)
- ``# noqa: SLF001 -- internal handoff`` (double hyphen)

What the rule leaves alone:

- ``# noqa: ARG002 - runner contract`` (the accepted form).
- ``# noqa: PLC0415`` with no trailing explanation (nothing to
  separate).
- ``# noqa: ARG002 (runner contract uses now_ms)``: the parenthetical
  form is an accepted alternative, not the em-dash drift class this
  rule targets.

Scope: ``libraries/*/src/``, ``workbench/*/src/``,
``support/test_harness/src/``.  Only ``.py`` files carry these inline
suppressions; ``tests/`` and ``docs/`` are out of scope.

Self-scope: the rule resolves ``src`` directories under
``<repo_root>/libraries/`` and ``<repo_root>/workbench/`` plus
``<repo_root>/support/test_harness/src``.  In a tree without those (a
downstream user workspace), it returns no findings, a silent no-op.

Suppression: add ``CHU031`` to the line's own noqa list
(``# noqa: ARG002, CHU031``) when an em-dash genuinely belongs.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU031"

#: A ``noqa:`` (with codes) or ``pragma: no cover`` directive followed
#: by a drifted separator (em-dash, en-dash, or double hyphen) and at
#: least one more non-space character of explanation.  The accepted
#: ``" - "`` separator and the bare-directive / parenthetical forms
#: don't match.
_DRIFTED_SEPARATOR = re.compile(
    r"#\s*(?:noqa:\s*[A-Z0-9, ]+|pragma:\s*no cover)\s+(—|–|--)\s+\S",
)

#: The rule's own source and tests carry drifted-separator examples as
#: docstring and fixture data; exempting them keeps the rule off its own
#: documentation.  Paths are repo-root-relative.
_SELF_EXEMPT_RELPATHS: frozenset[Path] = frozenset({
    Path("workbench/checks/src/chumicro_checks/rules/chu031.py"),
    Path("workbench/checks/tests/test_chu031.py"),
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
    test_harness_src_dir = repo_root / "support" / "test_harness" / "src"
    if test_harness_src_dir.is_dir():
        roots.append(test_harness_src_dir)
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
        if line_suppresses(line, _RULE_CODE):
            continue
        match = _DRIFTED_SEPARATOR.search(line)
        if match is None:
            continue
        findings.append(
            Finding(
                path=filepath,
                line=line_number,
                code=_RULE_CODE,
                message=(
                    f"noqa / pragma explanation separator {match.group(1)!r} "
                    f"is not the accepted form; use ' - ' (space hyphen "
                    f"space) to separate the suppression from its explanation"
                ),
            )
        )
    return findings


class CHU031_NoqaSeparator(Rule):
    code = _RULE_CODE
    description = (
        "noqa / pragma explanation uses ' - ' (space hyphen space), "
        "not an em-dash / en-dash / double-hyphen separator"
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


CHU031 = CHU031_NoqaSeparator()
