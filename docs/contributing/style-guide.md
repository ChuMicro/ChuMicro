# Style Guide

This is the definitive reference for code style in the Chumicro workspace. All code — library, infrastructure, and tests — follows these conventions unless explicitly noted.

The linter (`python scripts/run.py lint`) enforces most of these automatically. If lint passes, you're almost certainly fine. This guide explains what the rules are, why they exist, and what to do when the linter flags something.

## Baseline

We follow [PEP 8](https://peps.python.org/pep-0008/), the standard Python style guide, with a **100-character line limit** (configured in `pyproject.toml`). This is enforced automatically by [Ruff](https://docs.astral.sh/ruff/), a fast Python linter. You don't need to memorize PEP 8 — Ruff tells you when something is off.

## Naming

We use descriptive names and avoid abbreviations that require mental translation. The goal is that someone reading your code for the first time can understand what a variable holds without checking its assignment.

| Rule | Example | Enforced by |
|---|---|---|
| No single-letter variables (except `_`) | `index`, not `i`; `error`, not `e`; `key`, not `k` | `CHU001` linter |
| No banned abbreviations | `environment`, not `env`; `buffer`, not `buf`; `source`, not `src`; `command`, not `cmd`; `message`, not `msg`; `error`, not `err`; `reference`, not `ref` | `CHU001` linter |
| Banned abbreviations as suffixes too | `base_reference`, not `base_ref`; `build_environment`, not `build_env` | `CHU001` linter |
| Short-but-complete words are fine | `dir`, `key`, `tag`, `raw`, `pin`, `led`, `ok`, `end`, `args`, `config` | — |
| Suppress with `# noqa: CHU001` | Only when matching an upstream API (e.g., `micropython.const(x)`) | — |

**Why:** Code is read far more often than it is written. Descriptive names remove the mental step of translating abbreviations. Longer names also push lines past the 100-character limit, which forces multi-line formatting — each argument on its own line is easier to scan, diff, and blame. ([Decision 0022](plans/decisions/0022-naming-conventions.md))

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

([Decision 0021](plans/decisions/0021-docstring-type-policy.md))

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

([Decision 0021](plans/decisions/0021-docstring-type-policy.md))

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

Microcontrollers have limited RAM and no virtual memory. These patterns help library code run efficiently on constrained devices. They apply to **publishable library code under `libraries/`** and **`support/test_harness/`** — other infrastructure code (`scripts/`, rest of `support/`) runs on CPython and should use standard Python conventions.

| Pattern | Why |
|---|---|
| Pre-allocate `bytearray` in constructor, reuse with `readinto()` | Avoid repeated allocation |
| `memoryview` for slicing | Avoid copies |
| `const()` for numeric constants (import from `micropython`) | Compiler optimization |
| Cache frequently used attributes in local variables | Reduce attribute lookups in hot paths |
| Avoid dynamic string building in loops | GC pressure |

You don't need to apply these patterns from day one — they matter most in performance-sensitive code. If you're writing your first library, focus on correctness first and optimize later.

## What the linter checks

`python scripts/run.py lint` runs two tools back to back. If both pass, your code is style-correct.

**Ruff** — a fast Python linter that enforces:

| Rule set | What it catches |
|---|---|
| `E` — pycodestyle errors | Whitespace, indentation, line length, blank lines |
| `F` — pyflakes | Unused imports, undefined names, redefined variables |
| `I` — isort | Import ordering (stdlib → third-party → local, alphabetized) |
| `B` — bugbear | Common pitfalls like mutable default arguments, bare `except:`, unused loop variables |
| `UP` — pyupgrade | Modernization — replaces old syntax with newer Python equivalents |

**CHU001** — a custom naming check that catches:

- Single-letter variable names (`i` → `index`, `e` → `error`)
- Banned abbreviations used alone (`env` → `environment`, `buf` → `buffer`)
- Banned abbreviations as suffixes (`base_ref` → `base_reference`, `build_env` → `build_environment`)

If lint passes, your style is correct. You don't need to memorize any of this — the error messages tell you exactly what to fix and why.

