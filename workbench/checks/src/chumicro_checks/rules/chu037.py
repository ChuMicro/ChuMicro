"""CHU037: no em-dashes in user-facing prose.

The style guide's Voice section bans the em-dash outright in prose
documentation: READMEs, guides, contributing pages, troubleshooting
pages, demo walkthroughs, and the templates that scaffold any of
those.  The ban was first enforced by a manual sweep (2026-07-19),
and nine days later 74 user-facing files carried the character again
because nothing gated it.  This rule is the gate.

Scope: markdown prose a user or contributor reads.

* The root front doors (``README.md``, ``INSTALL.md``,
  ``CONTRIBUTING.md``, ``SECURITY.md``, ``CODE_OF_CONDUCT.md``,
  ``AGENTS.md``).
* ``docs/`` except ``docs/superpowers/`` (session working notes, not
  reader-facing pages).
* ``demos/``, ``libraries/``, ``workbench/``, and ``support/``
  markdown, excluding anything under a ``tests/``,
  ``functional_tests/``, or ``fixtures/`` directory (test fixtures are
  data, not prose).
* ``.github/PULL_REQUEST_TEMPLATE.md`` (the one reader-facing markdown
  file under ``.github/``; the skills tree there is agent tooling with
  its own conventions).
* Markdown scaffolding templates (``*.md.template``) under
  ``workbench/workspace/src/chumicro_workspace/_payloads/`` and
  ``scripts/templates/``, so a fresh scaffold can't reintroduce the
  character.

``plans/`` is deliberately out of scope: decision records and the
work queue are journal prose with their own conventions.

Suppression: ``<!-- noqa: CHU037 -->`` on the offending line, for the
rare line that must quote an em-dash (for example, a style-guide
"before" sample demonstrating the defect).
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU037"

_EM_DASH = "—"

#: Root-level files scanned individually.
_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "INSTALL.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "AGENTS.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

#: Directories walked for ``.md`` files.
_PROSE_DIRECTORIES: tuple[str, ...] = (
    "docs",
    "demos",
    "libraries",
    "workbench",
    "support",
)

#: Directories walked for ``*.md.template`` scaffolding files.
_TEMPLATE_DIRECTORIES: tuple[str, ...] = (
    "workbench/workspace/src/chumicro_workspace/_payloads",
    "scripts/templates",
)

#: Path components that take a file out of scope: test trees hold
#: fixture data, and docs/superpowers holds session working notes.
_EXCLUDED_PARTS: frozenset[str] = frozenset({
    "tests",
    "functional_tests",
    "fixtures",
    "superpowers",
})


def _in_scope(filepath: Path, repo_root: Path) -> bool:
    try:
        relative_parts = filepath.relative_to(repo_root).parts
    except ValueError:
        return False
    return not any(part in _EXCLUDED_PARTS for part in relative_parts)


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _EM_DASH not in line:
            continue
        if line_suppresses(line, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=line_number,
                code=_RULE_CODE,
                message=(
                    "em-dash in user-facing prose; rewrite with a period, "
                    "comma, colon, or parentheses (style guide, Voice)"
                ),
            )
        )
    return findings


class CHU037_EmDashProse(Rule):
    code = _RULE_CODE
    description = (
        "no em-dashes in user-facing prose: markdown docs and the "
        "templates that scaffold them"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for name in _ROOT_FILES:
            candidate = repo_root / name
            if candidate.is_file():
                findings.extend(_check_file(candidate))
        for relative in _PROSE_DIRECTORIES:
            for filepath in iter_text_files(
                repo_root / relative, suffixes=(".md",)
            ):
                if _in_scope(filepath, repo_root):
                    findings.extend(_check_file(filepath))
        for relative in _TEMPLATE_DIRECTORIES:
            for filepath in iter_text_files(
                repo_root / relative, suffixes=(".template",)
            ):
                if filepath.name.endswith(".md.template") and _in_scope(
                    filepath, repo_root
                ):
                    findings.extend(_check_file(filepath))
        return findings


CHU037 = CHU037_EmDashProse()
