"""CircuitPython bootstrap code generator.

Generates inline code blocks that can be sent through the
CircuitPython raw REPL.  Two builders share the same helper-function
prefix:

- :func:`build_circuitpython_bootstrap_scripts` is the test-harness
  flavor.  Registers library modules via the class-as-module
  pattern (no ``types.ModuleType`` on CircuitPython), inlines a test
  file, and runs it through ``chumicro_test_harness.runner.run_module``.
- :func:`build_circuitpython_deploy_scripts` is the deploy flavor.
  Registers every non-entrypoint file as an importable module, then
  ``exec()``-s the entrypoint as ``__main__``.  No test-harness
  dependency is needed, and the deploy tail is two lines long, kept
  as an inline string constant rather than a separate template file.

Both share the static helper functions in
``circuitpython_bootstrap_template.txt`` (read once per builder
call).  ``_register_stub`` and ``_populate_module`` are universal.
Only the dynamic parts (module sources, entrypoint / test source,
filter) are generated here.

"""

from __future__ import annotations

import ast
from pathlib import Path

from .protocol import validate_entrypoint_in_files
from .source_minify import _DocstringStripper

_TEMPLATE_PATH = Path(__file__).parent / "circuitpython_bootstrap_template.txt"

# CircuitPython raw-REPL execution is more reliable when large inline test
# payloads are sent as multiple smaller scripts instead of one giant block.
# The transport picks a runtime-specific budget at execution time.
DEFAULT_INLINE_SCRIPT_BUDGET_BYTES = 48 * 1024

_HELPER_AND_SETUP_MARKER = "# Pass 1: register empty stubs so import statements resolve."
_TEST_EXECUTION_MARKER = "# Execute the test file."

#: Inline tail for RAM-mode deploy bootstrap.  Kept as a string
#: constant rather than a template file because it is two
#: statements long, dwarfed by the helpers.  ``_retry_deferred`` is
#: defined by the shared helper script, and ``$ENTRYPOINT_SOURCE``
#: gets replaced with a ``repr()``-safe Python string literal at
#: generation time.  Passing an explicit ``__name__`` makes
#: ``if __name__ == '__main__':`` blocks in user entrypoints behave
#: the way they would after an ordinary boot.
_DEPLOY_EXECUTION_TEMPLATE = (
    "_retry_deferred()\n"
    "_materialize_lazy_exports()\n"
    "exec($ENTRYPOINT_SOURCE, {'__name__': '__main__'})"
)


class CircuitpythonBootstrapTooLargeError(ValueError):
    """Raised when an inline CircuitPython bootstrap is too large to send safely."""


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

    prelude = _build_shared_prelude(staged_sources, max_chunk_size_bytes)

    final_script = _build_test_execution_script(test_file, name_filter=name_filter)
    _validate_script_size(
        f"test execution for {test_file.name}",
        final_script,
        max_chunk_size_bytes,
    )

    return [*prelude, final_script]


def build_circuitpython_deploy_scripts(
    files: dict[str, bytes],
    entrypoint: str,
    *,
    max_chunk_size_bytes: int = DEFAULT_INLINE_SCRIPT_BUDGET_BYTES,
) -> list[str]:
    """Generate raw-REPL scripts for CircuitPython RAM-mode deploy.

    The returned scripts inject every non-entrypoint file as an
    importable module via ``sys.modules``, then ``exec()`` the
    entrypoint as ``__main__``.  No ``chumicro_test_harness``
    dependency is required on the device.

    Module naming follows CircuitPython's ``sys.path`` convention:
    files under ``/lib/`` are stripped of that prefix, so
    ``/lib/foo.py`` registers as ``foo`` and
    ``/lib/foo/bar.py`` as ``foo.bar``.  Files at the device root
    (``/foo.py``) register as top-level ``foo``.  Non-``.py`` files
    are silently skipped.  RAM-mode deploy has no device filesystem
    to write them to, so shipping non-Python assets requires flash
    mode.

    Args:
        files: On-device-path -> bytes mapping.
        entrypoint: On-device path exec'd as ``__main__``.  Must be
            a key of *files*.
        max_chunk_size_bytes: Maximum encoded size for any single
            submitted raw REPL script.  Defaults to
            :data:`DEFAULT_INLINE_SCRIPT_BUDGET_BYTES`; pass a tighter
            budget derived from ``gc.mem_free()`` when known.

    Returns:
        Ordered list of Python source strings to execute sequentially.

    Raises:
        ValueError: *entrypoint* is missing from *files* or
            *max_chunk_size_bytes* is not positive.
        CircuitpythonBootstrapTooLargeError: A single chunk exceeds
            *max_chunk_size_bytes*.
    """
    if max_chunk_size_bytes <= 0:
        raise ValueError("max_chunk_size_bytes must be positive")
    validate_entrypoint_in_files(files, entrypoint)

    entrypoint_source = _decode_file_content(files[entrypoint])

    staged_sources: list[tuple[str, str]] = []
    for device_path in sorted(files):
        if device_path == entrypoint:
            continue
        module_name = _derive_module_name(device_path)
        if module_name is None:
            continue
        staged_sources.append(
            (module_name, _decode_file_content(files[device_path])),
        )

    prelude = _build_shared_prelude(staged_sources, max_chunk_size_bytes)

    final_script = _DEPLOY_EXECUTION_TEMPLATE.replace(
        "$ENTRYPOINT_SOURCE", _escape_source(entrypoint_source),
    )
    _validate_script_size(
        f"deploy execution for {entrypoint}",
        final_script,
        max_chunk_size_bytes,
    )

    return [*prelude, final_script]


def _decode_file_content(content: bytes | str) -> str:
    """Return *content* as a ``str``, decoding UTF-8 bytes when needed."""
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8")
    return content


def _derive_module_name(device_path: str) -> str | None:
    """Convert an on-device path to a dotted Python module name.

    Returns ``None`` for paths that cannot be imported inline:
    non-``.py`` files (assets, ``.toml``, ``.json``) and paths that
    reduce to an empty name.

    Examples:

    ============================= =========
    Device path                   Module
    ============================= =========
    ``/lib/foo.py``               ``foo``
    ``/lib/foo/__init__.py``      ``foo``
    ``/lib/foo/bar.py``           ``foo.bar``
    ``/foo.py``                   ``foo``
    ``/settings.toml``            ``None``
    ``/``                         ``None``
    ============================= =========
    """
    stripped = device_path.lstrip("/")
    if stripped.startswith("lib/"):
        stripped = stripped[len("lib/"):]
    if not stripped.endswith(".py"):
        return None
    if stripped.endswith("/__init__.py"):
        stripped = stripped[: -len("/__init__.py")]
    else:
        stripped = stripped[: -len(".py")]
    if not stripped:
        return None
    return stripped.replace("/", ".")


def _escape_source(source_text: str) -> str:
    """Escape source code for embedding as a Python string literal.

    Args:
        source_text: Raw Python source code.

    Returns:
        A Python string literal suitable for embedding in generated code.
    """
    # Use repr() for safe escaping, which handles all special characters.
    return repr(source_text)


def _build_shared_prelude(
    staged_sources: list[tuple[str, str]],
    max_chunk_size_bytes: int,
) -> list[str]:
    """Return the helper + stub + population scripts every CircuitPython
    RAM-mode bootstrap builder runs first.

    Test and deploy bootstraps share these three setup steps verbatim:
    helper definitions, then stub registration, then module population.
    Building them here once keeps the class-as-module machinery out of
    each builder.
    """
    helper_script = _build_helper_script()
    _validate_script_size(
        "bootstrap helpers", helper_script, max_chunk_size_bytes,
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
            (module_name, _build_population_block(module_name, source_text))
            for module_name, source_text in staged_sources
        ],
        max_chunk_size_bytes,
    )
    return [helper_script, *stub_scripts, *population_scripts]


def _build_helper_script() -> str:
    """Return the setup script that defines helper functions once."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    helper_template = template.split(_HELPER_AND_SETUP_MARKER, maxsplit=1)[0]
    deferred_retry_helper = """
def _retry_deferred():
    while _deferred:
        remaining=[]
        progress_made=False
        for module_name, source_code in _deferred:
            try:
                _populate_module(module_name, source_code)
                progress_made=True
            except ImportError:
                remaining.append((module_name, source_code))
        if not progress_made:
            raise ImportError(
                'Unresolved module dependencies: ' + ', '.join(
                    module_name for module_name, _ in remaining
                )
            )
        _deferred[:]=remaining
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
        "_retry_deferred()\n"
        "_materialize_lazy_exports()\n"
        + test_execution_template
        .replace("$TEST_SOURCE", escaped_test)
        .replace("$FILTER_REPR", filter_repr)
    ).strip()


def _build_population_block(module_name: str, source_text: str) -> str:
    """Return the population block for one staged module."""
    escaped_source = _escape_source(_prepare_inline_source(source_text))
    return "\n".join([
        f"_m={module_name!r};_s={escaped_source}",
        "try:_populate_module(_m,_s)",
        "except ImportError:_deferred.append((_m,_s))",
    ])


def _prepare_inline_source(source_text: str) -> str:
    """Return RAM-mode inline source with docstrings and comments removed.

    Parses, drops every docstring, and unparses; the unparse also discards
    ``#`` comments and surplus whitespace, shrinking the embedded payload
    hardest, which matters because RAM-mode source is packed into
    size-bounded raw-REPL chunks.  Returns the text unchanged when it does
    not parse.
    """
    try:
        syntax_tree = ast.parse(source_text)
    except SyntaxError:
        return source_text

    stripped_tree = _DocstringStripper().visit(syntax_tree)
    ast.fix_missing_locations(stripped_tree)
    return ast.unparse(stripped_tree)


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
