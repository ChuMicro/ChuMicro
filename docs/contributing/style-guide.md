# Style Guide

This is the definitive reference for code style in the ChuMicro workspace. All code — library, infrastructure, and tests — follows these conventions unless explicitly noted.

The linter (`python scripts/run.py lint`) enforces most of these automatically. If lint passes, you're almost certainly fine. This guide explains what the rules are, why they exist, and what to do when the linter flags something.

## Baseline

We follow [PEP 8](https://peps.python.org/pep-0008/), the standard Python style guide, with a **100-character line limit** (configured in `pyproject.toml`). This is enforced automatically by [Ruff](https://docs.astral.sh/ruff/), a fast Python linter. You don't need to memorize PEP 8 — Ruff tells you when something is off.

## Naming

We use descriptive names so everyone can read the code without extra context. The linter catches common abbreviations and suggests the descriptive name for you.

| Rule | Example | Enforced by |
|---|---|---|
| No single-letter variables (except `_` and for-loop targets) | `index`, not `i` in assignments; `for i in range(10)` is fine | `CHU001` linter |
| Abbreviations we spell out | `environment`, not `env`; `buffer`, not `buf`; `source`, not `src`; `command`, not `cmd`; `message`, not `msg`; `error`, not `err`; `reference`, not `ref`; `address`, not `addr`; `exception`, not `exc`; `execute`, not `exec` | `CHU001` linter |
| Spell them out as suffixes too | `base_reference`, not `base_ref`; `build_environment`, not `build_env` | `CHU001` linter |
| Short-but-complete words are fine | `dir`, `key`, `tag`, `raw`, `pin`, `led`, `ok`, `end`, `args`, `config` | — |
| For-loop targets are exempt | `for i in range(10)`, `for k, v in items()` | — |
| Suppress with `# noqa: CHU001` | Only when matching an upstream API that you cannot rename | — |

**Why:** We optimize for readability across experience levels — full words over abbreviations. Python's common abbreviations (`msg`, `err`, `exc`, `buf`) are instantly familiar to experienced developers but not self-explanatory to everyone. Newcomers, multilingual developers working across multiple languages, and non-native English speakers don't share that background — `exc` isn't obviously "exception" if you haven't seen it before. The full words save every future reader a mental lookup. The linter handles this automatically, so it doesn't cost you time. We know it feels different from other Python projects — that's intentional. ([Decision 0022](../../plans/decisions/0022-naming-conventions.md))

## Type annotations

Python type annotations tell readers (and tools) what types a function accepts and returns. We use them on all function and method signatures. They cost zero runtime overhead on embedded boards — both CircuitPython and MicroPython parse annotations but strip them at compile time.

Do not import `typing` in library code — the module doesn't exist on CircuitPython or MicroPython. Use the modern built-in syntax instead:

```python
# ✅ Works on all runtimes — PEP 604 / PEP 585 syntax
def read(self, timeout: int | None = None) -> bytes | None: ...
def process(self, items: list[int]) -> dict[str, int]: ...

# ❌ Requires typing module — fails on embedded runtimes
from typing import Optional, List
def read(self, timeout: Optional[int] = None) -> Optional[bytes]: ...
```

Infrastructure code (`scripts/`) may use `typing` imports since it runs only on CPython. Most of `support/` is also CPython-only, **except `support/test_harness/`** which runs on all three runtimes — treat it like library code.

([Decision 0021](../../plans/decisions/0021-docstring-type-policy.md))

## Docstrings

Every public function, method, and class needs a docstring. We use [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings): types go on annotations, descriptions go in docstrings. This avoids writing the type twice.

```python
def ticks_diff(end: int, start: int) -> int:
    """Signed difference between two tick values.

    Args:
        end: Later tick value.
        start: Earlier tick value.

    Returns:
        Signed difference in milliseconds.
    """
```

The sections you'll use most:

- **`Args:`** — `name: description` (no type in parens — it's already on the signature)
- **`Returns:`** — description only (no `type:` prefix)
- **`Raises:`** — `ExceptionType: description`

The docs build fails on [griffe](https://mkdocstrings.github.io/griffe/) warnings about missing or malformed sections, so you'll know right away if something needs fixing.

([Decision 0021](../../plans/decisions/0021-docstring-type-policy.md))

## String formatting

Use f-strings for all string formatting. They're the most readable option and work identically across all three runtimes.

```python
# ✅
print(f"Found {count} items in {directory}")

# ❌
print("Found %d items in %s" % (count, directory))
print("Found {} items in {}".format(count, directory))
```

## Memory patterns (library code only)

Microcontrollers have limited RAM and no virtual memory. These patterns help library code run efficiently on constrained devices. **You don't need to apply these patterns from day one** — they matter most in performance-sensitive code. If you're writing your first library, focus on correctness first and optimize later.

They apply to **publishable library code under `libraries/`** and **`support/test_harness/`** — other infrastructure code (`scripts/`, rest of `support/`) runs on CPython and should use standard Python conventions.

| Pattern | Why |
|---|---|
| Pre-allocate `bytearray` in constructor, reuse with `readinto()` | Avoid repeated allocation |
| `memoryview` for slicing | Avoid copies |
| `const()` for numeric constants (import from `micropython`) | Compiler optimization |
| Cache frequently used attributes in local variables | Reduce attribute lookups in hot paths |
| Avoid dynamic string building in loops | GC pressure |

<details>
<summary>Examples (expand when you're ready to optimize)</summary>

#### `const()` — compile-time constants

On MicroPython and CircuitPython, `const()` inlines the value at compile time instead of creating a runtime object. On CPython it doesn't exist, so every library that uses it needs a fallback:

```python
try:
    from micropython import const
except ImportError:

    def const(value: int) -> int:
        """Identity fallback so const() works on CPython."""
        return value

_PERIOD = const(1 << 29)       # inlined at compile time, no heap allocation
_MAX = const(_PERIOD - 1)
```

Prefix internal constants with `_` (module-private). See `libraries/timing/src/chumicro_timing/ticks.py` for a real example.

#### `memoryview` — zero-copy slicing

Normal `bytearray` slicing creates a copy every time. `memoryview` gives you a slice that points to the original data:

```python
# ❌ Each slice copies data
header = data[0:4]       # new bytearray allocated
payload = data[4:20]     # another new bytearray allocated

# ✅ Zero-copy — slices share the original buffer
view = memoryview(data)
header = view[0:4]       # no copy
payload = view[4:20]     # no copy
```

Combine with pre-allocated buffers for the full pattern:

```python
class PacketReader:
    """Incremental packet reader with zero-copy slicing."""

    def __init__(self, buffer_size: int = 64) -> None:
        self._buffer = bytearray(buffer_size)  # allocated once
        self._view = memoryview(self._buffer)   # reusable view

    def read_header(self, source: object) -> memoryview:
        """Read from source into the buffer, return the header slice."""
        source.readinto(self._buffer)
        return self._view[0:4]  # zero-copy slice
```

</details>


## Coverage exclusions

Every library must meet the **85 %** coverage threshold configured in `pyproject.toml` (`fail_under = 85`). Sometimes code genuinely can't be exercised in CPython tests — runtime-specific branches, hardware fallbacks, or defensive guards that only fire on a real board. Mark those lines so they don't drag down your coverage.

### `# pragma: no cover` — exclude a line or block

Add the comment to any line, `if` branch, or function that can't be tested on CPython:

```python
# Single line
x = board.D5  # pragma: no cover

# Entire branch
if sys.implementation.name == "circuitpython":  # pragma: no cover
    import neopixel
else:
    from chumicro_compat.stubs import neopixel

# Entire function (put it on the def line)
def _reset_hardware() -> None:  # pragma: no cover
    """Hard-reset the I2C bus — only works on real hardware."""
    ...
```

### Common patterns that already work

The `const()` fallback pattern used across libraries is already fully covered (both the `try` and `except` branches run on CPython). You usually don't need `# pragma: no cover` for it.

### When to use it

- **Runtime-only imports** (`import board`, `import neopixel`, etc.)
- **Hardware-specific branches** (`if sys.platform == "rp2":`)
- **Defensive guards** that only fire under conditions impossible to reproduce in tests (e.g., memory allocation failure on a 256 KB MCU)

### When NOT to use it

- Don't use it to hide untested business logic — write a test instead.
- Don't use it on code that *could* be tested with a fake or stub. If you can inject the dependency and test it, do that.
- If you're unsure, leave it uncovered and note it in your PR. A reviewer can help decide.

### Browsing coverage

After running tests, you can see exactly which lines are covered:

```bash
python -m coverage html
open htmlcov/index.html
```

Covered lines show in green, missed lines in red. Much easier than reading line numbers from the terminal output. (`htmlcov/` is gitignored.)


`python scripts/run.py lint` runs three tools back to back. If all three pass, your code is style-correct.

**Ruff** — a fast Python linter that enforces:

| Rule set | What it catches |
|---|---|
| `E` — pycodestyle errors | Whitespace, indentation, line length, blank lines |
| `F` — pyflakes | Unused imports, undefined names, redefined variables |
| `I` — isort | Import ordering (stdlib → third-party → local, alphabetized) |
| `B` — bugbear | Common pitfalls like mutable default arguments, bare `except:`, unused loop variables |
| `UP` — pyupgrade | Modernization — replaces old syntax with newer Python equivalents |

**`scripts/check_names.py` — `CHU001`** catches:

- Single-letter variable names in assignments, parameters, and function names (`x` → use a descriptive name, `e` → `error`)
- For-loop targets are exempt — `for i in range(10)` is fine
- Abbreviated names we prefer spelled out (`env` → `environment`, `buf` → `buffer`)
- Those same abbreviations as suffixes (`base_ref` → `base_reference`, `build_env` → `build_environment`)

**`scripts/check_whitespace.py` — `CHU002`–`CHU005`** catches whitespace bugs that diff noisily and are easy to miss in review:

| Rule | What it catches |
|---|---|
| `CHU002` | File does not end with exactly one newline |
| `CHU003` | More than two consecutive blank lines inside a file |
| `CHU004` | Trailing whitespace on any line |
| `CHU005` | Blank line immediately after a block opener (`def`, `class`, `if:`, `for:`, etc.) |

If lint passes, your style is correct. You don't need to memorize any of this — the error messages tell you exactly what to fix and why.
