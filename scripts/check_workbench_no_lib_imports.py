"""Lint that workbench packages do not import chumicro library packages (Decision 0052).

Walks every Python file under ``workbench/*/src/`` and flags any
``import chumicro_<libname>`` or ``from chumicro_<libname>``
statement where ``<libname>`` matches a package that lives under
``libraries/``.

Why this matters: ``libraries/`` packages target microcontroller
runtimes (CircuitPython, MicroPython, CPython-as-host-test-seam).
Their CPython compatibility exists for testing and dev, not as a
production runtime.  Workbench tools are CPython-only and ship to
laptops, so they should depend on third-party PyPI equivalents
(``pyserial``, ``msgpack``, ``ruamel.yaml``, etc.) rather than
device-shaped libraries that happen to import on CPython.

Templates and on-device payloads embedded as bytes (``.txt`` /
``.template`` files) are not scanned — those run on the device
and legitimately import library packages.

Suppression: ``# noqa: CHU007`` on the offending line.

Usage::

    python scripts/check_workbench_no_lib_imports.py
    python scripts/check_workbench_no_lib_imports.py [paths...]
    python scripts/run.py lint            # runs automatically alongside ruff
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from repo_layout import ROOT

_RULE_CODE = "CHU007"
_NOQA_TAG = "# " + "noqa"


def _library_package_names() -> set[str]:
    """Return the set of importable names for packages under ``libraries/``.

    A library at ``libraries/<name>/`` ships as ``chumicro_<name>``.
    """
    names: set[str] = set()
    libraries_dir = ROOT / "libraries"
    if not libraries_dir.is_dir():
        return names
    for child in sorted(libraries_dir.iterdir()):
        if (child / "pyproject.toml").is_file():
            names.add(f"chumicro_{child.name}")
    return names


def _scan_roots() -> list[Path]:
    """Return every ``workbench/<name>/src/`` directory."""
    roots: list[Path] = []
    workbench_dir = ROOT / "workbench"
    if not workbench_dir.is_dir():
        return roots
    for package_dir in sorted(workbench_dir.iterdir()):
        src_dir = package_dir / "src"
        if src_dir.is_dir():
            roots.append(src_dir)
    return roots


def _read_noqa_lines(source: str) -> set[int]:
    """Return 1-based line numbers carrying a CHU007-suppressing noqa."""
    suppressed: set[int] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        tag_pos = line.find(_NOQA_TAG)
        if tag_pos == -1:
            continue
        after = line[tag_pos + len(_NOQA_TAG):]
        if after.strip() == "" or _RULE_CODE in after:
            suppressed.add(line_number)
    return suppressed


def _top_level(dotted_name: str) -> str:
    """``'chumicro_wifi.adapters.cp'`` → ``'chumicro_wifi'``."""
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


def check_file(filepath: Path, library_packages: set[str]) -> list[str]:
    """Return formatted lint errors for *filepath* (empty when clean)."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(text, filename=str(filepath))
    except SyntaxError:
        return []

    noqa_lines = _read_noqa_lines(text)
    errors: list[str] = []
    relative = filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    for line_number, package_name in _violations_in_tree(tree, library_packages):
        if line_number in noqa_lines:
            continue
        errors.append(
            f"{relative}:{line_number}: {_RULE_CODE} workbench package imports "
            f"library package '{package_name}' — workbench is host-only; libraries "
            "target devices.  Use a third-party PyPI equivalent."
        )
    return errors


def _iter_python_files(path: Path) -> list[Path]:
    """Return every ``.py`` file under *path* (or *path* itself if it is one)."""
    if path.is_file():
        return [path] if path.suffix == ".py" else []
    if not path.is_dir():
        return []
    out: list[Path] = []
    for candidate in sorted(path.rglob("*.py")):
        if any(part == "__pycache__" for part in candidate.parts):
            continue
        out.append(candidate)
    return out


def check_paths(paths: list[str]) -> int:
    """Check the given paths for forbidden workbench-to-library imports."""
    library_packages = _library_package_names()
    all_errors: list[str] = []
    for path_str in paths:
        for filepath in _iter_python_files(Path(path_str)):
            all_errors.extend(check_file(filepath, library_packages))

    if all_errors:
        for error in all_errors:
            print(error)
        print(f"\nFound {len(all_errors)} workbench-to-library import(s).")
        print(
            "Workbench packages are host-only; library packages target devices.  "
            "Use a third-party PyPI equivalent (pyserial, msgpack, ruamel.yaml, etc.)."
        )
        print(f"Fix: switch to a host-side dep, or add '# noqa: {_RULE_CODE}' to suppress.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Optional paths to scan.  Defaults to every ``workbench/*/src/``
            tree under the workspace.
    """
    paths = argv if argv else [str(root) for root in _scan_roots()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
