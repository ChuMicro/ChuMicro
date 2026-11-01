"""CHU039: Python snippets in the docs parse and import names that exist.

Each ```` ```python ```` fence in a README or guide is code a beginner
pastes into ``code.py``.  A fence that fails to parse raises
``SyntaxError`` on its first run.  A fence that imports a name its
``chumicro_*`` module never defines raises ``ImportError``.

Scope: ```` ```python ```` and ```` ```py ```` fences in the root
``README.md``, ``docs/**/*.md``, ``libraries/*/README.md``,
``libraries/*/docs/*.md``, ``workbench/*/README.md``,
``workbench/*/docs/*.md``, and ``demos/**/README.md``.  Fences follow
CommonMark: backtick or tilde fences, flush left or indented under a
list item, closed by a fence of the same character at least as long.
A repo without those files gets no findings.

Flags:

* A fence body that fails ``ast.parse``.  The finding points at the line
  the parser reported.
* ``import chumicro_<x>[.<sub>]`` or ``from chumicro_<x>[.<sub>] import
  ...`` naming a module with no source, when the top-level
  ``chumicro_<x>`` package has source under ``libraries/*/src``,
  ``workbench/*/src``, or ``support/*/src``.  A ``chumicro_*`` package
  with no source in the repo, such as one installed from PyPI, goes
  unchecked.
* ``from chumicro_<x>[.<sub>] import Name`` where ``Name`` is absent
  from that module.  The rule reads each module's source with ``ast``
  and never imports it.  A module exports every name bound at module
  level (``def``, ``class``, assignment, ``import``, ``for``, ``with``,
  ``except ... as``), including bindings under a module-level ``if`` or
  ``try``.  It also exports every ``__all__`` entry and every
  identifier string inside its module-level ``__getattr__``, which
  covers PEP 562 lazy exports.  A package also exports its submodules.
  When another module in the same package exports ``Name``, the finding
  names that module.  Otherwise it names the closest exported name.

Fragment marker: ``<!-- fragment -->`` as the last non-blank line above
an opening fence marks a fence that shows part of a program, such as
the lines that change on another runtime.  The marker renders as
nothing.  It skips the parse check.  The import check still runs on a
fragment whose body parses.

Suppression:

* ``# noqa: CHU039`` on a line inside the fence mutes the finding on
  that line.
* ``<!-- noqa: CHU039 -->`` as the last non-blank line above the opening
  fence mutes every finding in that fence.

The fragment marker and the fence-wide ``noqa`` count only on a line
that holds HTML comments and nothing else, so a directive at the end of
a prose sentence stays with that sentence.
"""

from __future__ import annotations

import ast
import difflib
import re
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU039"

#: Fence info-string languages whose body is Python source.
_PYTHON_LANGUAGES: frozenset[str] = frozenset({"python", "py"})

#: Opening fence: indent, run of three or more backticks or tildes, info string.
_FENCE_OPEN = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")

#: A line that holds one or more HTML comments and nothing else.
_COMMENT_ONLY_LINE = re.compile(r"^\s*(?:<!--(?:(?!-->).)*-->\s*)+$")

#: The fragment marker inside a comment-only line.
_FRAGMENT_MARKER = re.compile(r"<!--\s*fragment\s*-->")

#: Top-level trees whose ``*/src`` directories hold importable source.
_SOURCE_TREES: tuple[str, ...] = ("libraries", "workbench", "support")

#: Module roots the import checks cover.
_CHECKED_ROOT_PREFIX = "chumicro_"

#: Expressions with a scope of their own: a lambda's parameters and a
#: comprehension's loop variable stay out of the module namespace.
_SCOPED_EXPRESSIONS: tuple[type[ast.AST], ...] = (
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@dataclass(frozen=True)
class _Fence:
    """One Python fence: its opening line, body, and the marker line above it."""

    open_line: int
    body: str
    marker_line: str


def _markdown_files(repo_root: Path) -> list[Path]:
    """Return every in-scope markdown file under *repo_root*, sorted per tree."""
    files: list[Path] = []
    root_readme = repo_root / "README.md"
    if root_readme.is_file():
        files.append(root_readme)
    files.extend(iter_text_files(repo_root / "docs", suffixes=(".md",)))
    for tree in ("libraries", "workbench"):
        tree_dir = repo_root / tree
        if not tree_dir.is_dir():
            continue
        files.extend(
            path for path in sorted(tree_dir.glob("*/README.md")) if path.is_file()
        )
        files.extend(
            path for path in sorted(tree_dir.glob("*/docs/*.md")) if path.is_file()
        )
    files.extend(
        path
        for path in iter_text_files(repo_root / "demos", suffixes=(".md",))
        if path.name == "README.md"
    )
    return files


def _is_closing_fence(line: str, fence: str) -> bool:
    """Return whether *line* closes a fence opened with *fence*."""
    stripped = line.strip()
    if not stripped or stripped[0] != fence[0]:
        return False
    return len(stripped) >= len(fence) and stripped == fence[0] * len(stripped)


def _strip_indent(line: str, indent: int) -> str:
    """Return *line* with up to *indent* leading whitespace characters removed."""
    removable = len(line) - len(line.lstrip(" \t"))
    return line[min(indent, removable):]


def _python_fences(lines: list[str]) -> Iterator[_Fence]:
    """Yield every Python fence in markdown *lines*.

    The body loses up to the opening fence's indentation from each line,
    so a fence nested under a list item parses as flush-left source.  An
    unclosed fence runs to the end of the file.
    """
    previous_text = ""
    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN.match(lines[index])
        if opening is None or (
            opening["fence"][0] == "`" and "`" in opening["info"]
        ):
            if lines[index].strip():
                previous_text = lines[index]
            index += 1
            continue
        fence = opening["fence"]
        indent = len(opening["indent"])
        info_words = opening["info"].split()
        language = info_words[0].lower() if info_words else ""
        open_index = index
        index += 1
        body: list[str] = []
        while index < len(lines) and not _is_closing_fence(lines[index], fence):
            body.append(_strip_indent(lines[index], indent))
            index += 1
        if language in _PYTHON_LANGUAGES:
            marker_line = (
                previous_text if _COMMENT_ONLY_LINE.match(previous_text) else ""
            )
            yield _Fence(
                open_line=open_index + 1,
                body="\n".join(body) + "\n",
                marker_line=marker_line,
            )
        previous_text = lines[index] if index < len(lines) else ""
        index += 1


def _bound_names(node: ast.AST) -> Iterator[str]:
    """Yield every name *node*'s module-level code binds, recursively.

    A nested def or class yields its own name and nothing from its body.
    A module-level ``__getattr__`` also yields each identifier string in
    its body: those are the PEP 562 lazy exports it serves.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child.name
            if child.name == "__getattr__":
                yield from _getattr_names(child)
            continue
        if isinstance(child, _SCOPED_EXPRESSIONS):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            yield child.id
        elif isinstance(child, ast.Import):
            for alias in child.names:
                yield alias.asname or alias.name.split(".")[0]
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                if alias.name != "*":
                    yield alias.asname or alias.name
        elif isinstance(child, ast.ExceptHandler) and child.name:
            yield child.name
        yield from _bound_names(child)


def _getattr_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[str]:
    """Yield every identifier-shaped string constant inside *function*."""
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.isidentifier()
        ):
            yield node.value


def _dunder_all_names(tree: ast.Module) -> Iterator[str]:
    """Yield the string entries of every top-level ``__all__`` literal."""
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            targets = [statement.target]
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        if isinstance(statement.value, (ast.List, ast.Tuple)):
            for element in statement.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    yield element.value


def _parse(source: str) -> ast.Module:
    """Return the syntax tree of *source*, raising ``SyntaxError`` when it fails to parse.

    ``_parse`` silences ``SyntaxWarning``, which an invalid escape such as
    ``"\\d"`` raises.  Under ``python -W error`` that warning becomes an
    exception, and a valid fence would read as broken.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


class _SourceIndex:
    """Module names and exports read from the repo's ``*/src`` trees.

    ``_SourceIndex`` maps each dotted module name to its source file, or
    to ``None`` for a package directory without an ``__init__.py``.  A
    module is parsed on its first lookup and cached, so a run parses
    only the modules the docs import.
    """

    def __init__(self, repo_root: Path) -> None:
        self._module_files: dict[str, Path | None] = {}
        self._submodules: dict[str, set[str]] = {}
        self._exports: dict[str, frozenset[str] | None] = {}
        for tree in _SOURCE_TREES:
            tree_dir = repo_root / tree
            if not tree_dir.is_dir():
                continue
            for source_dir in sorted(tree_dir.glob("*/src")):
                for filepath in iter_text_files(source_dir, suffixes=(".py",)):
                    self._register(source_dir, filepath)

    def _register(self, source_dir: Path, filepath: Path) -> None:
        parts = list(filepath.relative_to(source_dir).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            return
        for depth in range(1, len(parts) + 1):
            self._module_files.setdefault(".".join(parts[:depth]), None)
            if depth > 1:
                parent = ".".join(parts[: depth - 1])
                self._submodules.setdefault(parent, set()).add(parts[depth - 1])
        self._module_files[".".join(parts)] = filepath

    def has_package(self, module: str) -> bool:
        """Return whether the top-level package of *module* has source here."""
        return module.split(".")[0] in self._module_files

    def has_module(self, module: str) -> bool:
        """Return whether *module* is a source file or package directory."""
        return module in self._module_files

    def exports(self, module: str) -> frozenset[str] | None:
        """Return the names *module* exports, or ``None`` when its source fails to parse."""
        if module not in self._exports:
            self._exports[module] = self._read_exports(module)
        return self._exports[module]

    def _read_exports(self, module: str) -> frozenset[str] | None:
        names = set(self._submodules.get(module, ()))
        filepath = self._module_files.get(module)
        if filepath is None:
            return frozenset(names)
        try:
            tree = _parse(filepath.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return None
        names.update(_bound_names(tree))
        names.update(_dunder_all_names(tree))
        return frozenset(names)

    def defining_module(self, module: str, name: str) -> str | None:
        """Return the first module in *module*'s top-level package exporting *name*.

        Modules are searched in sorted order, skipping *module* itself, so
        the answer is the same on every run.
        """
        package = module.split(".")[0]
        for candidate in sorted(self._module_files):
            if candidate == module:
                continue
            if candidate != package and not candidate.startswith(package + "."):
                continue
            names = self.exports(candidate)
            if names is not None and name in names:
                return candidate
        return None


def _missing_name_message(index: _SourceIndex, module: str, name: str) -> str:
    """Return the finding text for ``from module import name`` with *name* absent."""
    message = f"`{name}` is absent from `{module}`"
    home = index.defining_module(module, name)
    if home is not None:
        return f"{message}. `{home}` exports it"
    exports = index.exports(module) or frozenset()
    close = difflib.get_close_matches(name, sorted(exports), n=1)
    if close:
        return f"{message}. `{close[0]}` is the closest name it exports"
    return message


def _import_findings(
    tree: ast.Module, index: _SourceIndex,
) -> Iterator[tuple[int, str]]:
    """Yield ``(fence line, message)`` for each unresolved ``chumicro_*`` import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if not module.startswith(_CHECKED_ROOT_PREFIX):
                    continue
                if index.has_package(module) and not index.has_module(module):
                    yield alias.lineno, f"module `{module}` has no source in this repo"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not module.startswith(_CHECKED_ROOT_PREFIX):
                continue
            if not index.has_package(module):
                continue
            if not index.has_module(module):
                yield node.lineno, f"module `{module}` has no source in this repo"
                continue
            exports = index.exports(module)
            if exports is None:
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in exports:
                    yield alias.lineno, _missing_name_message(index, module, alias.name)


def _fence_findings(fence: _Fence, index: _SourceIndex) -> Iterator[tuple[int, str]]:
    """Yield ``(markdown line, message)`` for each problem in *fence*."""
    try:
        tree = _parse(fence.body)
    except SyntaxError as error:
        if _FRAGMENT_MARKER.search(fence.marker_line):
            return
        body_lines = max(fence.body.count("\n"), 1)
        fence_line = min(max(error.lineno or 1, 1), body_lines)
        yield (
            fence.open_line + fence_line,
            f"Python fence fails to parse ({error.msg}). Fix the code, or mark "
            f"a partial snippet with `<!-- fragment -->` on the line above the fence",
        )
        return
    for fence_line, message in _import_findings(tree, index):
        yield fence.open_line + fence_line, message


def _check_file(filepath: Path, index: _SourceIndex) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    findings: list[Finding] = []
    for fence in _python_fences(lines):
        if line_suppresses(fence.marker_line, _RULE_CODE):
            continue
        for line, message in _fence_findings(fence, index):
            if line <= len(lines) and line_suppresses(lines[line - 1], _RULE_CODE):
                continue
            findings.append(
                Finding(path=filepath, line=line, code=_RULE_CODE, message=message)
            )
    return findings


class CHU039_DocSnippetsResolve(Rule):
    code = _RULE_CODE
    description = (
        "Python fences in the docs parse, and their `chumicro_*` imports "
        "resolve against the repo's source"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        markdown_files = _markdown_files(repo_root)
        if not markdown_files:
            return []
        index = _SourceIndex(repo_root)
        findings: list[Finding] = []
        for filepath in markdown_files:
            findings.extend(_check_file(filepath, index))
        return findings


CHU039 = CHU039_DocSnippetsResolve()
