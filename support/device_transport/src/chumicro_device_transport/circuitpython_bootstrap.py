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

# Inline raw-REPL payloads that grow beyond this size have proven unreliable
# on constrained CircuitPython boards such as the Pi Pico W. Flash deploy
# mode avoids the giant in-memory bootstrap entirely.
MAX_INLINE_BOOTSTRAP_BYTES = 64 * 1024

# ESP32-family CircuitPython boards have enough headroom for substantially
# larger inline payloads, so they bypass the conservative size guard used
# for constrained boards.
_ESP32_BOARD_TYPE_PREFIX = "esp32"


class CircuitpythonBootstrapTooLargeError(ValueError):
    """Raised when an inline CircuitPython bootstrap is too large to send safely."""


def build_circuitpython_bootstrap(
    staged_sources: list[tuple[str, str]],
    test_file: Path,
    *,
    name_filter: str | None = None,
    board_type: str = "",
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
        board_type: Optional board identifier from ``devices.yml``.
            Used to apply conservative RAM-payload limits only on
            constrained CircuitPython boards.

    Returns:
        Python source code string for raw REPL execution.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    # Build stub registration lines.
    stub_lines = [
        f"_register_stub({module_name!r})"
        for module_name, _source_text in staged_sources
    ]

    # Build population lines with ImportError deferral.
    population_lines: list[str] = []
    for module_name, source_text in staged_sources:
        escaped_source = _escape_source(source_text)
        population_lines.extend([
            "try:",
            f"    _populate_module({module_name!r}, {escaped_source})",
            "except ImportError:",
            f"    _deferred.append(({module_name!r}, {escaped_source}))",
        ])

    # Read and escape the test file.
    test_source = test_file.read_text(encoding="utf-8")
    escaped_test = _escape_source(test_source)

    filter_repr = repr(name_filter) if name_filter else "None"

    bootstrap_script = (
        template
        .replace("$STUB_REGISTRATIONS", "\n".join(stub_lines))
        .replace("$MODULE_POPULATIONS", "\n".join(population_lines))
        .replace("$TEST_SOURCE", escaped_test)
        .replace("$FILTER_REPR", filter_repr)
    )

    inline_bootstrap_limit_bytes = _inline_bootstrap_limit_bytes(board_type)
    bootstrap_size_bytes = len(bootstrap_script.encode("utf-8"))
    if (
        inline_bootstrap_limit_bytes is not None
        and bootstrap_size_bytes > inline_bootstrap_limit_bytes
    ):
        raise CircuitpythonBootstrapTooLargeError(
            "CircuitPython inline bootstrap is too large for reliable RAM "
            f"execution on constrained boards ({bootstrap_size_bytes} bytes > "
            f"{inline_bootstrap_limit_bytes} bytes). Use flash deploy mode or "
            "set deploy_mode: flash for this board in devices.yml."
        )

    return bootstrap_script


def _escape_source(source_text: str) -> str:
    """Escape source code for embedding as a Python string literal.

    Args:
        source_text: Raw Python source code.

    Returns:
        A Python string literal suitable for embedding in generated code.
    """
    # Use repr() for safe escaping — it handles all special characters.
    return repr(source_text)


def _inline_bootstrap_limit_bytes(board_type: str) -> int | None:
    """Return the inline bootstrap size limit for a CircuitPython board.

    ESP32-family boards tolerate substantially larger inline payloads in RAM
    mode, so the conservative 64 KiB guard is skipped for them. Unknown or
    empty board types keep the conservative guard.

    Args:
        board_type: Board identifier from ``devices.yml``.

    Returns:
        Maximum allowed inline bootstrap size in bytes, or ``None`` when the
        board family is known to handle larger payloads reliably.
    """
    normalized_board_type = board_type.strip().lower()
    if normalized_board_type.startswith(_ESP32_BOARD_TYPE_PREFIX):
        return None
    return MAX_INLINE_BOOTSTRAP_BYTES
