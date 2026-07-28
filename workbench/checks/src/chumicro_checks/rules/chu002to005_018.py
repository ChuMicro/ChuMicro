"""CHU002–CHU005 + CHU018: newline and whitespace rules.

The whitespace family.  Each rule walks the same set of text files
(any ``.py``, ``.md``, ``.yml``,
``.yaml``, ``.toml``, ``.txt``, ``.cfg``, ``.ini``, ``.json`` under
``libraries/``, ``workbench/``, ``support/``, ``scripts/``,
``plans/``, ``docs/``) and emits its specific finding shape.

Repo-root loose files are deliberately *not* scanned: the root mixes
gitignored user-local files (``devices.yml``, ``secrets.toml``) with
tracked ones, and the walker reads the filesystem, not git. Scanning
root would false-positive on per-user files.

* CHU002: file does not end with exactly one newline.  Structural;
  no per-line suppression.
* CHU003: more than two consecutive blank lines.  Structural; no
  per-line suppression.
* CHU004: trailing whitespace on a line.  Suppress with
  ``# noqa: CHU004`` on the line.
* CHU018: CR / CRLF line endings; LF only.  Structural; no per-line
  suppression (a CR is never wanted in this repo's text files).
* CHU005: blank line immediately after a block opener (``def``,
  ``class``, ``if``, ``for``, ``while``, ``with``, ``try``, ``else``,
  ``elif``, ``except``, ``finally``, ``match``, ``case``, and the
  ``async`` variants).  A multi-line header whose ``):`` closes on its
  own line counts too.  Python files only.  Suppress with
  ``# noqa: CHU005`` on the block-opener line (the blank line itself
  has no code to attach a comment to).  An exception fires for the
  idiomatic blank-line-before-nested-definition pattern (import-fallback
  blocks, conditional definitions): if the next non-blank line is a
  ``def`` or ``class``, the blank stays clean.

Self-scope: scans the top-level ``scripts/`` / ``plans/`` / ``docs/``
trees, the workspace-template user-content trees, and inside each
``libraries|workbench|support/<pkg>/`` package its ``src/``, ``tests/``,
``functional_tests/``, ``examples/``, and ``docs/`` subdirectories plus
the package-root ``README.md``.  Package-root metadata
(``pyproject.toml``, ``mkdocs.yml``, ``VERSION``) stays out of scope.
In a tree without any of those, every rule returns no findings, a
silent no-op.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule

_CHU002 = "CHU002"
_CHU003 = "CHU003"
_CHU004 = "CHU004"
_CHU005 = "CHU005"
_CHU018 = "CHU018"

_SCANNED_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".md", ".yml", ".yaml", ".toml",
    ".txt", ".cfg", ".ini", ".json",
})

_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__", "site", ".git", ".tools", "node_modules",
    "dist", "build", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".venv",
})

#: Top-level directories scanned in their entirety (no per-package
#: subdir restriction).  Includes the chumicro mono-repo's
#: ``scripts/`` plus the workspace-template's top-level user-content
#: trees, which don't have the per-package ``src/tests/...`` shape
#: a chumicro library has.
_SCAN_TOP_LEVELS: tuple[str, ...] = (
    "scripts", "plans", "docs",
    "packages", "projects", "shared", "examples", "tests",
)

#: Per-package parent directories.  Inside each package directory, the
#: listed subdirs are scanned in full, plus the package-root files in
#: :data:`_PACKAGE_ROOT_FILES`.  pyproject.toml, mkdocs.yml, VERSION,
#: and other package-root metadata stay out of the linter's scope.
_PACKAGE_PARENTS: tuple[str, ...] = ("libraries", "workbench", "support")
_PACKAGE_SUBDIRS: tuple[str, ...] = (
    "src", "tests", "functional_tests", "examples", "docs",
)

#: Package-root prose files scanned directly (the rest of the package
#: root is metadata).  The README is the most user-visible publishable
#: prose a package ships, so its whitespace hygiene matters as much as
#: the source tree's.
_PACKAGE_ROOT_FILES: tuple[str, ...] = ("README.md",)

_BLOCK_OPENER = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?(?:def |class |if |elif |for |while |with |except\b"
    r"|match |case ).*:"
    r"|"
    r"(?:else|try|finally)\s*:"
    r")\s*(?:#.*)?\s*$"
)

#: The final physical line of a *multi-line* block opener: a lone
#: closing paren (optionally followed by a ``-> return-annotation``)
#: then the terminating colon.  A multi-line ``def`` / ``class`` / ``if``
#: header whose ``):`` lands on its own line ends here, so a blank line
#: after it is still a blank-after-opener.  A multi-line function *call*
#: closes on a bare ``)`` with no colon and does not match.
_MULTILINE_OPENER_CLOSE = re.compile(r"^\s*\)\s*(?:->[^:]+)?:\s*(?:#.*)?$")

_DEFINITION = re.compile(r"^\s*(?:async\s+)?(?:def |class )")


def _is_skipped_part(part: str) -> bool:
    return part in _SKIP_DIRS or part.endswith(".egg-info")


def _iter_text_files(repo_root: Path) -> Iterator[Path]:
    """Yield every text file in the rule's scope under *repo_root*.

    Walks ``scripts/`` recursively plus every
    ``<libraries|workbench|support>/<pkg>/<src|tests|functional_tests|examples>/``
    subdirectory that exists.
    """
    roots: list[Path] = []
    for top_level in _SCAN_TOP_LEVELS:
        candidate = repo_root / top_level
        if candidate.is_dir():
            roots.append(candidate)
    package_root_files: list[Path] = []
    for parent_name in _PACKAGE_PARENTS:
        parent = repo_root / parent_name
        if not parent.is_dir():
            continue
        for package in sorted(parent.iterdir()):
            if not package.is_dir():
                continue
            for subdir_name in _PACKAGE_SUBDIRS:
                subdir = package / subdir_name
                if subdir.is_dir():
                    roots.append(subdir)
            for filename in _PACKAGE_ROOT_FILES:
                candidate = package / filename
                if candidate.is_file():
                    package_root_files.append(candidate)

    seen: set[Path] = set()
    for root in roots:
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file():
                continue
            if candidate.suffix not in _SCANNED_SUFFIXES:
                continue
            if any(_is_skipped_part(part) for part in candidate.parts):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate

    for candidate in package_root_files:
        if candidate.suffix not in _SCANNED_SUFFIXES:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        yield candidate


def _read_text(filepath: Path) -> str | None:
    try:
        return filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _check_chu002(filepath: Path, text: str) -> list[Finding]:
    """File must end with exactly one newline (or be empty)."""
    if text == "":
        return []
    if not text.endswith("\n"):
        return [
            Finding(
                path=filepath,
                line=1,
                code=_CHU002,
                message="file does not end with a newline",
            )
        ]
    if text.endswith("\n\n"):
        stripped = text.rstrip("\n")
        extra = len(text) - len(stripped)
        return [
            Finding(
                path=filepath,
                line=len(text.splitlines()) + 1,
                code=_CHU002,
                message=f"file ends with {extra} newlines instead of 1",
            )
        ]
    return []


def _check_chu003(filepath: Path, text: str) -> list[Finding]:
    """No more than two consecutive blank lines."""
    findings: list[Finding] = []
    consecutive_blank = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "":
            consecutive_blank += 1
        else:
            consecutive_blank = 0
        if consecutive_blank == 3:
            findings.append(
                Finding(
                    path=filepath,
                    line=line_number,
                    code=_CHU003,
                    message="more than 2 consecutive blank lines",
                )
            )
    return findings


def _check_chu004(filepath: Path, text: str) -> list[Finding]:
    """No trailing whitespace on any line."""
    findings: list[Finding] = []
    is_python = filepath.suffix == ".py"
    for line_number, raw in enumerate(text.splitlines(keepends=True), start=1):
        line = raw.rstrip("\n\r")
        if line == line.rstrip():
            continue
        if is_python and line_suppresses(raw, _CHU004):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=line_number,
                code=_CHU004,
                message="trailing whitespace",
            )
        )
    return findings


def _check_chu018(filepath: Path, _text: str) -> list[Finding]:
    """Files must use LF line endings. No CR or CRLF.

    Reads raw bytes: the shared text reader opens in universal-newline
    mode, which silently translates ``\\r\\n`` to ``\\n`` before any
    rule sees it. A CR check has to bypass it.  One finding per
    file (at the first offending line). A mixed-ending file is one
    defect, not one per line.
    """
    try:
        data = filepath.read_bytes()
    except OSError:
        return []
    carriage = data.find(b"\r")
    if carriage == -1:
        return []
    line_number = data.count(b"\n", 0, carriage) + 1
    return [
        Finding(
            path=filepath,
            line=line_number,
            code=_CHU018,
            message="CR / CRLF line ending (expected LF)",
        )
    ]


def _check_chu005(filepath: Path, text: str) -> list[Finding]:
    """No blank line immediately after a Python block opener."""
    if filepath.suffix != ".py":
        return []
    lines = text.splitlines(keepends=True)
    findings: list[Finding] = []
    prev_was_block_opener = False
    prev_line_text = ""
    in_triple_quote = False

    for line_number, raw in enumerate(lines, start=1):
        stripped = raw.rstrip("\n\r")
        is_blank = stripped.strip() == ""

        if not is_blank:
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote

        if prev_was_block_opener and is_blank:
            if not line_suppresses(prev_line_text, _CHU005):
                next_content = ""
                for lookahead in lines[line_number:]:
                    candidate = lookahead.strip()
                    if candidate:
                        next_content = candidate
                        break
                if not _DEFINITION.match(next_content):
                    findings.append(
                        Finding(
                            path=filepath,
                            line=line_number,
                            code=_CHU005,
                            message="blank line after block opener",
                        )
                    )

        if not is_blank and not in_triple_quote:
            prev_was_block_opener = bool(
                _BLOCK_OPENER.match(stripped)
                or _MULTILINE_OPENER_CLOSE.match(stripped)
            )
        else:
            prev_was_block_opener = False
        prev_line_text = raw

    return findings


_CHECKERS = {
    _CHU002: _check_chu002,
    _CHU003: _check_chu003,
    _CHU004: _check_chu004,
    _CHU005: _check_chu005,
    _CHU018: _check_chu018,
}


class _WhitespaceRule(Rule):
    """Common scaffolding for the four whitespace rules."""

    def __init__(self, *, code: str, description: str) -> None:
        self.code = code
        self.description = description

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        checker = _CHECKERS[self.code]
        for filepath in _iter_text_files(repo_root):
            text = _read_text(filepath)
            if text is None:
                continue
            findings.extend(checker(filepath, text))
        return findings


CHU002 = _WhitespaceRule(
    code=_CHU002,
    description="file must end with exactly one newline",
)

CHU003 = _WhitespaceRule(
    code=_CHU003,
    description="no more than two consecutive blank lines",
)

CHU004 = _WhitespaceRule(
    code=_CHU004,
    description="no trailing whitespace",
)

CHU005 = _WhitespaceRule(
    code=_CHU005,
    description="no blank line immediately after a Python block opener",
)

CHU018 = _WhitespaceRule(
    code=_CHU018,
    description="files must use LF line endings (no CR / CRLF)",
)
