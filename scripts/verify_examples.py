"""AST-based example verification for library examples.

Verifies that examples have valid syntax and resolvable imports using
static analysis — no execution required.  Hardware examples (files named
``circuitpython_*.py`` or ``micropython_*.py``) only verify ``chumicro_*``
imports; platform-specific imports are skipped.

See ``plans/decisions/0013-docs-and-examples-standards.md``.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

from discovery import ROOT

#: Filename prefixes that indicate hardware-specific examples.
#: For these, only chumicro_* imports are verified — platform modules
#: like ``board``, ``digitalio``, ``machine`` are skipped.
_HARDWARE_PREFIXES = ("circuitpython_", "micropython_")


def _is_chumicro_module(name: str) -> bool:
    """Return whether a module name belongs to this workspace."""
    return name.startswith("chumicro_")


def _check_imports(
    tree: ast.Module,
    rel_path: str,
    hardware: bool,
) -> bool:
    """Walk the AST and verify that all imports resolve.

    Returns True if all imports are valid, False if any fail.
    """
    ok = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if hardware and not _is_chumicro_module(alias.name):
                    continue
                try:
                    importlib.import_module(alias.name)
                except ImportError:
                    print(
                        f"  FAIL: {rel_path}  "
                        f"(cannot import module '{alias.name}')"
                    )
                    ok = False
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue  # relative import without module — skip
            if hardware and not _is_chumicro_module(node.module):
                continue
            try:
                module = importlib.import_module(node.module)
            except ImportError:
                print(
                    f"  FAIL: {rel_path}  "
                    f"(cannot import module '{node.module}')"
                )
                ok = False
                continue
            for alias in node.names:
                if not hasattr(module, alias.name):
                    print(
                        f"  FAIL: {rel_path}  "
                        f"('{node.module}' has no attribute "
                        f"'{alias.name}')"
                    )
                    ok = False
    return ok


def verify_examples(package_dirs: list[Path]) -> int:
    """Verify examples have valid syntax and resolvable imports.

    Uses static analysis (AST parsing + ``importlib`` resolution) rather
    than executing examples.

    Discovers ``examples/*.py`` in each selected library, then for each:

    1. Compiles the source to catch syntax errors.
    2. Walks the AST to extract ``import`` and ``from … import …`` statements.
    3. Resolves each imported module via ``importlib`` and verifies that
       specific names (``from X import Y``) exist on the module.

    Hardware examples (files named ``circuitpython_*.py`` or
    ``micropython_*.py``) may import modules unavailable on CPython
    (``board``, ``digitalio``, ``machine``, etc.).  For these, only
    ``chumicro_*`` imports are verified — platform-specific imports are
    skipped.
    """
    # Ensure library src/ dirs are importable.
    src_dirs = [
        str(package_dir / "src") for package_dir in package_dirs
        if (package_dir / "src").is_dir()
    ]
    saved_path = sys.path[:]
    for src_dir in src_dirs:
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

    examples: list[tuple[str, Path]] = []
    for package_dir in package_dirs:
        examples_dir = package_dir / "examples"
        if not examples_dir.is_dir():
            continue
        for py_file in sorted(examples_dir.glob("*.py")):
            relative_path = py_file.relative_to(ROOT)
            examples.append((str(relative_path), py_file))

    if not examples:
        print("No examples found for the selected packages.")
        sys.path[:] = saved_path
        return 0

    failures = 0
    for rel_path, py_file in examples:
        print(f"  checking {rel_path}")
        source = py_file.read_text(encoding="utf-8")
        hardware = py_file.name.startswith(_HARDWARE_PREFIXES)

        # 1. Syntax check.
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            print(f"  FAIL: {rel_path}  (syntax error: {exc})")
            failures += 1
            continue

        # 2. Verify imports.
        if not _check_imports(tree, rel_path, hardware):
            failures += 1
        else:
            label = f"  OK:   {rel_path}"
            if hardware:
                label += "  (hardware)"
            print(label)

    sys.path[:] = saved_path

    if failures:
        print(f"\n{failures} example(s) failed.")
        return 1

    print(f"\nAll {len(examples)} example(s) verified.")
    return 0
