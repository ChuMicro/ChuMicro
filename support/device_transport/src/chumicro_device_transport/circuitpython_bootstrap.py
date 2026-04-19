"""CircuitPython bootstrap code generator.

Generates a single inline code block that can be sent through the
CircuitPython raw REPL.  The generated code:

1. Registers library modules via the class-as-module pattern (no
   ``types.ModuleType`` on CircuitPython).
2. Inlines the test harness source.
3. Execs the test file and runs it through the harness.

The static helper functions live in
``circuitpython_bootstrap_template.py`` and are included verbatim.
Only the dynamic parts (module sources, test source, filter) are
generated here.

See Decision 0027 for the class-as-module pattern and CircuitPython
constraints.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE_PATH = Path(__file__).parent / "circuitpython_bootstrap_template.txt"

# CircuitPython raw-REPL execution is more reliable when large inline test
# payloads are sent as multiple smaller scripts instead of one giant block.
# The transport picks a runtime-specific budget at execution time.
DEFAULT_INLINE_SCRIPT_BUDGET_BYTES = 48 * 1024

_HELPER_AND_SETUP_MARKER = "# Pass 1: register empty stubs so import statements resolve."
_TEST_EXECUTION_MARKER = "# Execute the test file."


class CircuitpythonBootstrapTooLargeError(ValueError):
    """Raised when an inline CircuitPython bootstrap is too large to send safely."""


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
        name_filter: Optional substring filter passed to ``run_module``.

    Returns:
        Python source code string for raw REPL execution.
    """
    return "\n\n".join(build_circuitpython_bootstrap_scripts(
        staged_sources,
        test_file,
        name_filter=name_filter,
        max_chunk_size_bytes=1024 * 1024 * 1024,
    ))


def build_circuitpython_bootstrap_scripts(
    staged_sources: list[tuple[str, str]],
    test_file: Path,
    *,
    name_filter: str | None = None,
    max_chunk_size_bytes: int = DEFAULT_INLINE_SCRIPT_BUDGET_BYTES,
) -> list[str]:
    """Generate chunked raw-REPL scripts for CircuitPython RAM-mode tests.

    CircuitPython raw REPL buffers and compiles each submitted script before it
    executes. Large one-shot payloads can therefore exhaust heap even when the
    final imported modules would fit. This builder splits the inline bootstrap
    into smaller scripts that can be executed sequentially in one interpreter
    session.

    Args:
        staged_sources: List of ``(dotted_module_name, source_text)`` tuples.
        test_file: Path to the test file to execute.
        name_filter: Optional substring filter passed to ``run_module``.
        max_chunk_size_bytes: Maximum encoded size for any single submitted raw
            REPL script.

    Returns:
        Ordered list of Python source strings to execute sequentially.
    """
    if max_chunk_size_bytes <= 0:
        raise ValueError("max_chunk_size_bytes must be positive")

    helper_script = _build_helper_script()
    _validate_script_size(
        "bootstrap helpers",
        helper_script,
        max_chunk_size_bytes,
    )

    stub_scripts = _chunk_script_blocks(
        [
            (module_name, f"_register_stub({module_name!r})")
            for module_name, _source_text in staged_sources
        ],
        max_chunk_size_bytes,
    )

    population_scripts = _chunk_script_blocks(
        [
            (
                module_name,
                _build_population_block(module_name, source_text),
            )
            for module_name, source_text in staged_sources
        ],
        max_chunk_size_bytes,
    )

    final_script = _build_test_execution_script(test_file, name_filter=name_filter)
    _validate_script_size(
        f"test execution for {test_file.name}",
        final_script,
        max_chunk_size_bytes,
    )

    return [helper_script, *stub_scripts, *population_scripts, final_script]


def _escape_source(source_text: str) -> str:
    """Escape source code for embedding as a Python string literal.

    Args:
        source_text: Raw Python source code.

    Returns:
        A Python string literal suitable for embedding in generated code.
    """
    # Use repr() for safe escaping — it handles all special characters.
    return repr(source_text)


def _build_helper_script() -> str:
    """Return the setup script that defines helper functions once."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    helper_template = template.split(_HELPER_AND_SETUP_MARKER, maxsplit=1)[0]
    deferred_retry_helper = """
def _retry_deferred():
    while _deferred:
        remaining = []
        progress_made = False
        for module_name, source_code in _deferred:
            try:
                _populate_module(module_name, source_code)
                progress_made = True
            except ImportError:
                remaining.append((module_name, source_code))
        if not progress_made:
            raise ImportError(
                'Unresolved module dependencies: ' + ', '.join(
                    module_name for module_name, _ in remaining
                )
            )
        _deferred[:] = remaining
"""
    return helper_template + deferred_retry_helper + "\n_deferred = []\n"


def _build_test_execution_script(
    test_file: Path,
    *,
    name_filter: str | None,
) -> str:
    """Return the final script that resolves deferred imports and runs tests."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    test_execution_template = template.split(_TEST_EXECUTION_MARKER, maxsplit=1)[1]
    test_source = test_file.read_text(encoding="utf-8")
    escaped_test = _escape_source(test_source)
    filter_repr = repr(name_filter) if name_filter else "None"
    return (
        "_retry_deferred()\n\n"
        + _TEST_EXECUTION_MARKER
        + test_execution_template
        .replace("$TEST_SOURCE", escaped_test)
        .replace("$FILTER_REPR", filter_repr)
        .replace("$STUB_REGISTRATIONS", "")
        .replace("$MODULE_POPULATIONS", "")
    ).strip()


def _build_population_block(module_name: str, source_text: str) -> str:
    """Return the population block for one staged module."""
    escaped_source = _escape_source(source_text)
    return "\n".join([
        "try:",
        f"    _populate_module({module_name!r}, {escaped_source})",
        "except ImportError:",
        f"    _deferred.append(({module_name!r}, {escaped_source}))",
    ])


def _chunk_script_blocks(
    blocks: list[tuple[str, str]],
    max_chunk_size_bytes: int,
) -> list[str]:
    """Group named script blocks into scripts that stay under the size budget."""
    chunked_scripts: list[str] = []
    current_blocks: list[str] = []

    for block_name, block_text in blocks:
        _validate_script_size(block_name, block_text, max_chunk_size_bytes)
        candidate_blocks = [*current_blocks, block_text]
        candidate_script = "\n".join(candidate_blocks)
        if current_blocks and len(candidate_script.encode("utf-8")) > max_chunk_size_bytes:
            chunked_scripts.append("\n".join(current_blocks))
            current_blocks = [block_text]
        else:
            current_blocks = candidate_blocks

    if current_blocks:
        chunked_scripts.append("\n".join(current_blocks))

    return chunked_scripts


def _validate_script_size(
    script_name: str,
    script_text: str,
    max_chunk_size_bytes: int,
) -> None:
    """Raise when a single script exceeds the live RAM-mode chunk budget."""
    script_size_bytes = len(script_text.encode("utf-8"))
    if script_size_bytes <= max_chunk_size_bytes:
        return

    raise CircuitpythonBootstrapTooLargeError(
        "CircuitPython inline bootstrap chunk is larger than the live RAM "
        f"budget ({script_name}: {script_size_bytes} bytes > "
        f"{max_chunk_size_bytes} bytes). Use flash deploy mode for this test."
    )
