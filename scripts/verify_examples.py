"""AST-based example verification for library examples.

Verifies that examples have valid syntax and resolvable imports using
static analysis — no execution required.  Hardware examples (files named
``circuitpython_*.py`` or ``micropython_*.py``, or any file declaring
``__chumicro_runtimes__`` listing a non-CPython runtime) only verify
``chumicro_*`` imports; platform-specific imports are skipped.

Examples may also import sibling modules from their own ``examples/``
directory (e.g. a per-library ``helpers.py``).  The verifier puts each
example's parent directory on ``sys.path`` so those imports resolve.

See ``plans/decisions/0013-docs-and-examples-standards.md``.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

from repo_layout import ROOT

#: Filename prefixes that indicate hardware-specific examples.
#: For these, only chumicro_* imports are verified — platform modules
#: like ``board``, ``digitalio``, ``machine`` are skipped.
_HARDWARE_PREFIXES = ("circuitpython_", "micropython_")

#: Non-CPython runtime markers that flag a file as hardware-only.
_HARDWARE_RUNTIME_MARKERS = frozenset({"circuitpython", "micropython"})


def _is_chumicro_module(name: str) -> bool:
    """Return whether a module name belongs to this workspace.

    Args:
        name: Fully qualified module name.
    """
    return name.startswith("chumicro_")


def _has_hardware_runtime_marker(tree: ast.Module) -> bool:
    """Return ``True`` when the module declares a non-CPython runtime.

    Looks for a top-level ``__chumicro_runtimes__ = (...)`` assignment
    listing at least one non-CPython runtime (`circuitpython` or
    `micropython`).  Files that mark themselves as such use platform
    built-ins (`wifi`, `network`, `board`, `digitalio`, `machine`, …)
    that won't resolve on the host running this verifier.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__chumicro_runtimes__":
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
    """Walk the AST and verify that all imports resolve.

    Args:
        tree: Parsed AST of the example file.
        relative_path: Relative path to the file (for error messages).
        hardware: Whether the file is a hardware-specific example.

    Returns:
        ``True`` if all imports are valid, ``False`` if any fail.
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
                        f"  FAIL: {relative_path}  "
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
                    f"  FAIL: {relative_path}  "
                    f"(cannot import module '{node.module}')"
                )
                ok = False
                continue
            for alias in node.names:
                if not hasattr(module, alias.name):
                    print(
                        f"  FAIL: {relative_path}  "
                        f"('{node.module}' has no attribute "
                        f"'{alias.name}')"
                    )
                    ok = False
    return ok


def verify_examples(package_dirs: list[Path]) -> int:
    """Verify examples have valid syntax and resolvable imports.

    Uses static analysis (AST parsing + ``importlib`` resolution) rather
    than executing examples.

    Args:
        package_dirs: Package directories whose ``examples/`` to verify.

    Returns:
        Exit code (0 for success, 1 for failures).
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

    try:
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
            return 0

        failures = 0
        for relative_path, py_file in examples:
            print(f"  checking {relative_path}")
            source = py_file.read_text(encoding="utf-8")

            # 1. Syntax check.
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as error:
                print(f"  FAIL: {relative_path}  (syntax error: {error})")
                failures += 1
                continue

            hardware = (
                py_file.name.startswith(_HARDWARE_PREFIXES)
                or _has_hardware_runtime_marker(tree)
            )

            # Sibling imports (e.g. `from helpers import wifi_up`) resolve
            # against the example's own directory.  Add it temporarily.
            example_dir = str(py_file.parent)
            inserted_example_dir = example_dir not in sys.path
            if inserted_example_dir:
                sys.path.insert(0, example_dir)

            try:
                # 2. Verify imports.
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
