"""CHU007: workbench packages must not import library packages.

``libraries/<name>/`` packages target microcontroller runtimes; their
CPython compatibility exists for testing and dev, not as a production
runtime.  Workbench tools are CPython-only and ship to laptops, so
they should depend on third-party PyPI equivalents (``pyserial``,
``msgpack``, ``ruamel.yaml``, etc.) rather than device-shaped libraries
that happen to import on CPython.

The rule walks every ``.py`` file under ``workbench/<name>/src/`` and
flags ``import chumicro_<libname>`` or ``from chumicro_<libname>``
where ``<libname>`` matches a package directory under ``libraries/``.

Self-scope: a repo without both a ``workbench/`` and a ``libraries/``
tree returns no findings, a silent no-op.

Suppression: ``# noqa: CHU007`` on the import line.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU007"


def _library_package_names(repo_root: Path) -> set[str]:
    """Return the set of importable names for packages under ``libraries/``."""
    libraries_dir = repo_root / "libraries"
    if not libraries_dir.is_dir():
        return set()
    return {
        f"chumicro_{child.name}"
        for child in sorted(libraries_dir.iterdir())
        if (child / "pyproject.toml").is_file()
    }


def _workbench_src_roots(repo_root: Path) -> list[Path]:
    """Return every ``workbench/<name>/src/`` directory."""
    workbench_dir = repo_root / "workbench"
    if not workbench_dir.is_dir():
        return []
    roots: list[Path] = []
    for package_dir in sorted(workbench_dir.iterdir()):
        src_dir = package_dir / "src"
        if src_dir.is_dir():
            roots.append(src_dir)
    return roots


def _top_level(dotted_name: str) -> str:
    return dotted_name.split(".", 1)[0]


def _violations_in_tree(
    tree: ast.Module, library_packages: set[str]
) -> list[tuple[int, str]]:
    """Return ``(lineno, package_name)`` for each forbidden import."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level(alias.name)
                if top in library_packages:
                    found.append((node.lineno, top))
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = _top_level(node.module)
            if top in library_packages:
                found.append((node.lineno, top))
    return found


def _check_file(filepath: Path, library_packages: set[str]) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings

    source_lines = text.splitlines()
    findings: list[Finding] = []
    for line_number, package_name in _violations_in_tree(tree, library_packages):
        line_text = source_lines[line_number - 1] if line_number <= len(source_lines) else ""
        if line_suppresses(line_text, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=line_number,
                code=_RULE_CODE,
                message=(
                    f"workbench package imports library package "
                    f"'{package_name}': workbench is host-only; libraries "
                    f"target devices.  Use a third-party PyPI equivalent."
                ),
            )
        )
    return findings


class CHU007_WorkbenchNoLibImports(Rule):
    code = _RULE_CODE
    description = "workbench packages must not import chumicro_* library packages"

    def check(self, repo_root: Path) -> list[Finding]:
        library_packages = _library_package_names(repo_root)
        if not library_packages:
            return []
        roots = _workbench_src_roots(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file(filepath, library_packages))
        return findings


CHU007 = CHU007_WorkbenchNoLibImports()
