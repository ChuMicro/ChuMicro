"""AST-based example verification.

Verifies that example files (``<package>/examples/*.py``) have valid
syntax and resolvable imports using static analysis — no execution
required.

Hardware examples — files declaring ``__chumicro_runtimes__`` listing
a non-CPython runtime (CircuitPython or MicroPython) — verify only
``chumicro_*`` imports; platform built-ins (``board``, ``digitalio``,
``machine``, ``wifi``, ``network``) are skipped because they won't
resolve on the host.  The explicit marker is the contract.  Filename
conventions (``circuitpython_*.py`` / ``micropython_*.py``) are for
human discoverability only and have no bearing on the verification
path.

Examples may import sibling modules from their own ``examples/``
directory (e.g. a per-library ``helpers.py``).  Each example's parent
directory is added to ``sys.path`` for the duration of its verification.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

#: Non-CPython runtime markers that flag a file as hardware-only.
_HARDWARE_RUNTIME_MARKERS = frozenset({"circuitpython", "micropython"})


def _is_chumicro_module(name: str) -> bool:
    return name.startswith("chumicro_")


def _has_hardware_runtime_marker(tree: ast.Module) -> bool:
    """Return ``True`` when the module declares a non-CPython runtime.

    Looks for a top-level ``__chumicro_runtimes__ = (...)`` assignment
    listing at least one non-CPython runtime.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "__chumicro_runtimes__"):
                continue
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)):
                for elt in value.elts:
                    if (
                        isinstance(elt, ast.Constant)
                        and elt.value in _HARDWARE_RUNTIME_MARKERS
                    ):
                        return True
    return False


def _check_imports(
    tree: ast.Module,
    relative_path: str,
    hardware: bool,
) -> bool:
    """Walk the AST and verify that all imports resolve."""
    valid = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if hardware and not _is_chumicro_module(alias.name):
                    continue
                try:
                    importlib.import_module(alias.name)
                except ImportError:
                    print(
                        f"  FAIL: {relative_path}  "
                        f"(cannot import module '{alias.name}')",
                    )
                    valid = False
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if hardware and not _is_chumicro_module(node.module):
                continue
            try:
                module = importlib.import_module(node.module)
            except ImportError:
                print(
                    f"  FAIL: {relative_path}  "
                    f"(cannot import module '{node.module}')",
                )
                valid = False
                continue
            for alias in node.names:
                if not hasattr(module, alias.name):
                    print(
                        f"  FAIL: {relative_path}  "
                        f"('{node.module}' has no attribute "
                        f"'{alias.name}')",
                    )
                    valid = False
    return valid


def _collect_examples(
    package_dirs: list[Path],
    display_root: Path,
) -> list[tuple[str, Path]]:
    """Return ``(display_path, absolute_path)`` for every ``examples/*.py``."""
    examples: list[tuple[str, Path]] = []
    for package_dir in package_dirs:
        examples_dir = package_dir / "examples"
        if not examples_dir.is_dir():
            continue
        for example_file in sorted(examples_dir.glob("*.py")):
            try:
                display_path = str(example_file.relative_to(display_root))
            except ValueError:
                display_path = str(example_file)
            examples.append((display_path, example_file))
    return examples


def verify_examples(
    package_dirs: list[Path],
    *,
    display_root: Path | None = None,
) -> int:
    """Verify examples have valid syntax and resolvable imports.

    Each ``package_dirs`` entry should point at a package directory that
    contains an ``examples/`` subdirectory (e.g. ``libraries/timing``).
    For each ``examples/*.py``:

    1. Parse the file.  Syntax errors fail it.
    2. Detect whether it's hardware-only via the
       ``__chumicro_runtimes__`` marker.
    3. Walk imports — every ``chumicro_*`` import must resolve.
       Non-``chumicro_`` imports must resolve only on non-hardware files.
       Hardware files skip them so platform built-ins don't fail on the host.

    Args:
        package_dirs: Package directories whose ``examples/`` to verify.
        display_root: Path that relative-display paths are computed
            against.  Defaults to ``Path.cwd()``.  Purely cosmetic — the
            verifier walks ``package_dirs`` to find files regardless.

    Returns:
        Exit code (0 for success, 1 for failures).
    """
    if display_root is None:
        display_root = Path.cwd()

    src_dirs = [
        str(package_dir / "src") for package_dir in package_dirs
        if (package_dir / "src").is_dir()
    ]
    saved_path = sys.path[:]
    for src_dir in src_dirs:
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

    try:
        examples = _collect_examples(package_dirs, display_root)
        if not examples:
            print("No examples found for the selected packages.")
            return 0

        failures = 0
        for relative_path, example_file in examples:
            print(f"  checking {relative_path}")
            source = example_file.read_text(encoding="utf-8")

            try:
                tree = ast.parse(source, filename=str(example_file))
            except SyntaxError as error:
                print(f"  FAIL: {relative_path}  (syntax error: {error})")
                failures += 1
                continue

            hardware = _has_hardware_runtime_marker(tree)

            example_dir = str(example_file.parent)
            inserted_example_dir = example_dir not in sys.path
            if inserted_example_dir:
                sys.path.insert(0, example_dir)

            try:
                if not _check_imports(tree, relative_path, hardware):
                    failures += 1
                else:
                    label = f"  OK:   {relative_path}"
                    if hardware:
                        label += "  (hardware)"
                    print(label)
            finally:
                if inserted_example_dir:
                    sys.path.remove(example_dir)

        if failures:
            print(f"\n{failures} example(s) failed.")
            return 1

        print(f"\nAll {len(examples)} example(s) verified.")
        return 0
    finally:
        sys.path[:] = saved_path
