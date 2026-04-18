"""CircuitPython bootstrap code generator.

Generates a single inline code block that can be sent through the
CircuitPython raw REPL.  The generated code:

1. Registers library modules via the class-as-module pattern (no
   ``types.ModuleType`` on CircuitPython).
2. Inlines the test harness ``runner.py`` source.
3. Execs the test file and runs it through the harness.

See Decision 0027 for the class-as-module pattern and CircuitPython
constraints.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Pattern matching ``from .xxx import yyy`` or ``from . import yyy``.
_RELATIVE_IMPORT_RE = re.compile(
    r"^(\s*)from\s+\.(\w*)\s+import\s+",
    re.MULTILINE,
)


def _resolve_relative_imports(source_text: str, package: str) -> str:
    """Rewrite relative imports to absolute imports.

    CircuitPython's ``exec()`` does not support relative imports even
    when ``__package__`` is set in the namespace.  This rewrites
    ``from .foo import bar`` to ``from <package>.foo import bar`` and
    ``from . import bar`` to ``from <package> import bar``.

    Only single-dot relative imports are handled — deeper relative
    imports (``from ..foo``) are not used in this codebase.

    Args:
        source_text: Raw Python source code.
        package: The package name to resolve against.

    Returns:
        Source text with relative imports rewritten.
    """

    def _replace(match: re.Match) -> str:
        indent = match.group(1)
        relative_module = match.group(2)
        if relative_module:
            return f"{indent}from {package}.{relative_module} import "
        return f"{indent}from {package} import "

    return _RELATIVE_IMPORT_RE.sub(_replace, source_text)


def build_circuitpython_bootstrap(
    staged_sources: list[tuple[str, str]],
    test_file: Path,
    *,
    name_filter: str | None = None,
) -> str:
    """Generate a bootstrap code block for CircuitPython raw REPL execution.

    The generated code is self-contained — it does not rely on any
    ``import`` statements for ChuMicro libraries or the test harness.
    Everything is injected via ``exec()`` and ``sys.modules``.

    Args:
        staged_sources: List of ``(dotted_module_name, source_text)``
            tuples from the transport's ``stage()`` step.
        test_file: Path to the test file to execute.
        name_filter: Optional substring filter passed to
            ``run_module``.

    Returns:
        Python source code string for raw REPL execution.
    """
    lines: list[str] = []

    # Preamble: import sys for module registration.
    lines.append("import sys")
    lines.append("")

    # Module injection helper: class-as-module pattern.
    # CircuitPython lacks types.ModuleType, so we use a plain class
    # as a module stand-in.  A stub is registered first so that other
    # modules can ``import`` it; exec populates real attributes.
    lines.append("def _register_stub(module_name):")
    lines.append("    parts = module_name.rsplit('.', 1)")
    lines.append("    package = parts[0] if len(parts) > 1 else module_name")
    lines.append("    class _Mod:")
    lines.append("        pass")
    lines.append("    _Mod.__name__ = module_name")
    lines.append("    _Mod.__package__ = package")
    lines.append("    sys.modules[module_name] = _Mod")
    lines.append("    if len(parts) > 1:")
    lines.append("        parent = parts[0]")
    lines.append("        attr = parts[1]")
    lines.append("        if parent in sys.modules:")
    lines.append("            setattr(sys.modules[parent], attr, _Mod)")
    lines.append("")
    lines.append("def _populate_module(module_name, source_code):")
    lines.append("    parts = module_name.rsplit('.', 1)")
    lines.append("    package = parts[0] if len(parts) > 1 else module_name")
    lines.append("    namespace = {'__name__': module_name, '__package__': package}")
    lines.append("    exec(source_code, namespace)")
    lines.append("    module_obj = sys.modules[module_name]")
    lines.append("    for _key in namespace:")
    lines.append("        if not _key.startswith('__'):")
    lines.append("            setattr(module_obj, _key, namespace[_key])")
    lines.append("    if len(parts) > 1:")
    lines.append("        parent = parts[0]")
    lines.append("        attr = parts[1]")
    lines.append("        if parent in sys.modules:")
    lines.append("            setattr(sys.modules[parent], attr, module_obj)")
    lines.append("")

    # Pass 1: Register empty stubs for ALL modules so that import
    # statements resolve during exec.
    for module_name, _source_text in staged_sources:
        lines.append(f"_register_stub({module_name!r})")
    lines.append("")

    # Pass 2: Populate each module by exec'ing its source.  Relative
    # imports are rewritten to absolute because CircuitPython exec()
    # does not support relative imports.  Modules that import siblings
    # not yet populated get retried in pass 3.
    lines.append("_deferred = []")
    for module_name, source_text in staged_sources:
        parts = module_name.rsplit(".", 1)
        package = parts[0] if len(parts) > 1 else module_name
        resolved_source = _resolve_relative_imports(source_text, package)
        escaped_source = _escape_source(resolved_source)
        lines.append("try:")
        lines.append(
            f"    _populate_module({module_name!r}, {escaped_source})"
        )
        lines.append("except ImportError:")
        lines.append(
            f"    _deferred.append(({module_name!r}, {escaped_source}))"
        )
    lines.append("")

    # Pass 3: Retry deferred modules (forward references now resolved).
    lines.append("for _mod_name, _mod_src in _deferred:")
    lines.append("    _populate_module(_mod_name, _mod_src)")
    lines.append("")

    # Execute the test file.
    test_source = test_file.read_text(encoding="utf-8")
    escaped_test = _escape_source(test_source)
    lines.append("_test_namespace = {}")
    lines.append(f"exec({escaped_test}, _test_namespace)")
    lines.append("")

    # Convert namespace dict to attribute object for run_module.
    lines.append("class _TestModule:")
    lines.append("    pass")
    lines.append("for _key in _test_namespace:")
    lines.append("    setattr(_TestModule, _key, _test_namespace[_key])")
    lines.append("")

    # Import run_module from the injected harness and run.
    filter_repr = repr(name_filter) if name_filter else "None"
    lines.append(
        "from chumicro_test_harness.runner import run_module"
    )
    lines.append(
        f"run_module(_TestModule, name_filter={filter_repr})"
    )

    return "\n".join(lines) + "\n"


def _escape_source(source_text: str) -> str:
    """Escape source code for embedding as a Python string literal.

    Uses a triple-quoted raw-ish string with backslash escaping to
    safely embed arbitrary Python source code.

    Args:
        source_text: Raw Python source code.

    Returns:
        A Python string literal suitable for embedding in generated code.
    """
    # Use repr() for safe escaping — it handles all special characters.
    # For large sources, this is still more reliable than triple-quotes
    # which could contain unescaped triple-quote sequences.
    return repr(source_text)
