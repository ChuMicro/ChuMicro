"""CHU027: cross-site duplicate comment / docstring blocks.

The AGENTS.md "Code comments" non-negotiable forbids the same comment
repeated across many sites. Flash is ~800 KB total on the target
boards, and a comment pasted into ten files is ten copies of the same
bytes in the shipped bundle. Prose review reliably misses lexical
duplication across files, so this rule mechanizes the lexical half of
the discipline.

The engine: extract every comment block and module/class/function
docstring under publishable trees, normalize to a tuple of lowercased
word tokens, hash blocks at or above the minimum-token floor, and
flag fingerprints whose occurrences span enough sites that the
duplication is a signal rather than coincidence.

Calibration parameters (set conservative, bench against real corpus
before tightening):

* ``_MIN_TOKENS = 12``: short blocks share idiom language (``Returns
  the parsed result``) without being duplicative. The floor keeps the
  rule off that noise.
* ``_INTRA_PACKAGE_THRESHOLD = 3``: three matching blocks inside one
  package is the AGENTS.md "repeated across many sites" shape.
* ``_CROSS_PACKAGE_THRESHOLD = 2``: two matching blocks across two
  packages indicate one package should own the explanation and the
  other should cross-reference, rather than restating the same fact.

Scope: ``libraries/*/src/``, ``workbench/*/src/``,
``support/test_harness/``.  ``tests/`` and ``functional_tests/`` are
intentionally out of scope. Test files commonly share fixture
boilerplate that is correct duplication.

Suppression: ``# noqa: CHU027`` on the line carrying the first token
of a duplicate comment block, or on the ``def`` / ``class`` header line
for a function or class docstring, paired with the one-line *why*
AGENTS.md requires.  Module docstrings have no header line to carry the
marker and are deliberately not suppressible.
"""

from __future__ import annotations

import ast
import re
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU027"

_MIN_TOKENS = 12
_INTRA_PACKAGE_THRESHOLD = 3
_CROSS_PACKAGE_THRESHOLD = 2

#: Word-token extraction: alphanumeric, length >= 2 to skip noise.
_TOKEN = re.compile(r"\b[a-z][a-z0-9]+\b")


@dataclass(frozen=True)
class _Block:
    """One comment block or docstring extracted from a file."""

    filepath: Path
    line: int  # first line of the block
    package: str  # the package name from <parent>/<package>/...
    tokens: tuple[str, ...]
    suppressed: bool


def _package_of(filepath: Path, repo_root: Path) -> str:
    """Return the package identifier ``<parent>/<package>`` for *filepath*.

    Two files share a package iff they sit under the same
    ``libraries/<name>/`` or ``workbench/<name>/`` (or under
    ``support/test_harness/``).
    """
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return ""
    parts = relative.parts
    if len(parts) >= 2 and parts[0] in ("libraries", "workbench"):
        return f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2 and parts[0] == "support":
        return f"support/{parts[1]}"
    return parts[0] if parts else ""


def _normalize(text: str) -> tuple[str, ...]:
    """Lowercase + alphanumeric word-token sequence."""
    return tuple(_TOKEN.findall(text.lower()))


def _extract_comment_blocks(text: str, filepath: Path, package: str) -> list[_Block]:
    """Group consecutive ``#`` comments into blocks.

    A line carrying a ``# noqa: CHU027`` directive marks the whole
    block as suppressed AND is excluded from the content hashed for
    dedup matching. The marker affects only whether the finding is
    reported, not which blocks match.
    """
    blocks: list[_Block] = []
    try:
        tokens = list(tokenize.generate_tokens(StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    content_lines: list[str] = []
    block_start: int = 0
    last_line: int = -2
    block_suppressed = False
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        line_no = token.start[0]
        comment_text = token.string.lstrip("#").lstrip()
        is_noqa = line_suppresses(token.string, _RULE_CODE)
        if line_no != last_line + 1:
            if content_lines or block_suppressed:
                blocks.append(_make_block(
                    content_lines, block_start, filepath, package,
                    block_suppressed,
                ))
            content_lines = []
            block_suppressed = False
            block_start = line_no
        if is_noqa:
            block_suppressed = True
        else:
            content_lines.append(comment_text)
        last_line = line_no
    if content_lines or block_suppressed:
        blocks.append(_make_block(
            content_lines, block_start, filepath, package, block_suppressed,
        ))
    return blocks


def _make_block(
    lines: list[str], start: int, filepath: Path, package: str,
    suppressed: bool,
) -> _Block:
    joined = " ".join(lines)
    return _Block(
        filepath=filepath,
        line=start,
        package=package,
        tokens=_normalize(joined),
        suppressed=suppressed,
    )


def _extract_docstring_blocks(
    text: str, filepath: Path, package: str, source_lines: list[str],
) -> list[_Block]:
    """Yield one block per module / class / function docstring.

    A docstring is marked suppressed when its enclosing ``def`` /
    ``class`` / module header line above carries ``# noqa: CHU027``.
    The docstring body itself is the user-facing API doc, so the
    natural home for the marker is the surrounding scaffolding.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    blocks: list[_Block] = []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None:
            continue
        first = node.body[0] if node.body else None
        if not isinstance(first, ast.Expr) or not isinstance(
            first.value, ast.Constant,
        ):
            continue
        if not isinstance(first.value.value, str):
            continue
        # Class and function docstrings are suppressible by placing
        # a noqa marker for this rule on the def / class header line
        # above them. Module-level docstrings have no such header
        # line and are not suppressible through this check.
        suppressed = False
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            def_line = node.lineno
            if 1 <= def_line <= len(source_lines):
                if line_suppresses(source_lines[def_line - 1], _RULE_CODE):
                    suppressed = True
        blocks.append(_Block(
            filepath=filepath,
            line=first.lineno,
            package=package,
            tokens=_normalize(docstring),
            suppressed=suppressed,
        ))
    return blocks


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
    test_harness = repo_root / "support" / "test_harness"
    if test_harness.is_dir():
        roots.append(test_harness)
    return roots


def _collect_blocks(
    roots: list[Path], repo_root: Path,
) -> tuple[list[_Block], list[Finding]]:
    """Return the qualifying blocks and one syntax finding per unparseable file."""
    blocks: list[_Block] = []
    syntax_findings: list[Finding] = []
    for root in roots:
        for filepath in iter_text_files(root, suffixes=(".py",)):
            try:
                text = filepath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            tree, file_syntax = parse_or_syntax_finding(
                text, filepath, _RULE_CODE,
            )
            if tree is None:
                syntax_findings.extend(file_syntax)
                continue
            package = _package_of(filepath, repo_root)
            source_lines = text.splitlines()
            blocks.extend(_extract_comment_blocks(text, filepath, package))
            blocks.extend(_extract_docstring_blocks(
                text, filepath, package, source_lines,
            ))
    qualifying = [block for block in blocks if len(block.tokens) >= _MIN_TOKENS]
    return qualifying, syntax_findings


def _group_duplicates(blocks: list[_Block]) -> list[list[_Block]]:
    by_fingerprint: dict[tuple[str, ...], list[_Block]] = defaultdict(list)
    for block in blocks:
        by_fingerprint[block.tokens].append(block)
    duplicates: list[list[_Block]] = []
    for group in by_fingerprint.values():
        if len(group) < 2:
            continue
        packages = {block.package for block in group}
        if len(packages) == 1:
            if len(group) >= _INTRA_PACKAGE_THRESHOLD:
                duplicates.append(group)
        else:
            if len(packages) >= _CROSS_PACKAGE_THRESHOLD:
                duplicates.append(group)
    return duplicates


class CHU027_CrossSiteDuplicate(Rule):
    code = _RULE_CODE
    description = (
        "no cross-site duplicate comment / docstring blocks: explain "
        "once in a canonical home and cross-reference"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_roots(repo_root)
        if not roots:
            return []
        blocks, findings = _collect_blocks(roots, repo_root)
        for group in _group_duplicates(blocks):
            sites = ", ".join(
                f"{block.filepath.relative_to(repo_root)}:{block.line}"
                for block in group
            )
            for block in group:
                if block.suppressed:
                    continue
                findings.append(
                    Finding(
                        path=block.filepath,
                        line=block.line,
                        code=_RULE_CODE,
                        message=(
                            f"duplicate comment / docstring block "
                            f"({len(group)} sites, "
                            f"{len({block.package for block in group})} packages); "
                            f"explain once and cross-reference.  Sites: {sites}"
                        ),
                    )
                )
        return findings


CHU027 = CHU027_CrossSiteDuplicate()
