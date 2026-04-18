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

from pathlib import Path


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
    # CircuitPython lacks types.ModuleType, so we use a plain class.
    # exec() into a dict, then copy attributes to a class via setattr.
    lines.append("def _inject_module(module_name, source_code):")
    lines.append("    namespace = {}")
    lines.append("    exec(source_code, namespace)")
    lines.append("    class _Module:")
    lines.append("        pass")
    lines.append("    for _key in namespace:")
    lines.append("        if not _key.startswith('__'):")
    lines.append("            setattr(_Module, _key, namespace[_key])")
    lines.append("    # Preserve dunder attributes needed by import system.")
    lines.append("    _Module.__name__ = module_name")
    lines.append("    parts = module_name.rsplit('.', 1)")
    lines.append("    _Module.__package__ = parts[0] if len(parts) > 1 else module_name")  # noqa: E501
    lines.append("    sys.modules[module_name] = _Module")
    lines.append("    # If this is a submodule, attach to parent package.")
    lines.append("    if '.' in module_name:")
    lines.append("        parent_name = module_name.rsplit('.', 1)[0]")
    lines.append("        attr_name = module_name.rsplit('.', 1)[1]")
    lines.append("        if parent_name in sys.modules:")
    lines.append("            setattr(sys.modules[parent_name], attr_name, _Module)")
    lines.append("")

    # Register each library and harness module.
    # Order matters: __init__.py modules must come before submodules so
    # that the parent package exists in sys.modules when submodules try
    # to attach themselves.
    for module_name, source_text in staged_sources:
        # Skip test harness runner — it will be handled separately
        # as the entry point for running tests.
        escaped_source = _escape_source(source_text)
        lines.append(
            f"_inject_module({module_name!r}, {escaped_source})"
        )
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
        f"_exit_code = run_module(_TestModule, name_filter={filter_repr})"
    )
    lines.append("import sys as _sys")
    lines.append("_sys.exit(_exit_code)")

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
