# Style Guide

This is the definitive reference for code style in the Chumicro workspace. All code — library, infrastructure, and tests — follows these conventions unless explicitly noted.

The linter (`python scripts/run.py lint`) enforces most of these automatically. If lint passes, you're almost certainly fine.

## Baseline

[PEP 8](https://peps.python.org/pep-0008/) with a **100-character line limit** (configured in `pyproject.toml`). Enforced by [Ruff](https://docs.astral.sh/ruff/).

## Naming

Descriptive names. No abbreviations that require mental translation.

| Rule | Example | Enforced by |
|---|---|---|
| No single-letter variables (except `_`) | `index`, not `i`; `error`, not `e`; `key`, not `k` | `CHU001` linter |
| No banned abbreviations | `environment`, not `env`; `buffer`, not `buf`; `source`, not `src`; `command`, not `cmd`; `message`, not `msg`; `error`, not `err`; `reference`, not `ref` | `CHU001` linter |
| Banned abbreviations as suffixes too | `base_reference`, not `base_ref`; `build_environment`, not `build_env` | `CHU001` linter |
| Short-but-complete words are fine | `dir`, `key`, `tag`, `raw`, `pin`, `led`, `ok`, `end`, `args`, `config` | — |
| Suppress with `# noqa: CHU001` | Only when matching an upstream API (e.g., `micropython.const(x)`) | — |

**Why:** Code is read far more often than it is written. Descriptive names remove the mental step of translating abbreviations. Longer names also push lines past the 100-character limit, which forces multi-line formatting — each argument on its own line is easier to scan, diff, and blame. ([Decision 0022](plans/decisions/0022-naming-conventions.md))

## Type annotations

Use standard Python type annotations on all function and method signatures. Do not import `typing` in library code — it doesn't exist on CircuitPython or MicroPython.

```python
# ✅ Works on all runtimes — PEP 604 / PEP 585 syntax
def read(self, timeout: int | None = None) -> bytes | None: ...
def process(self, items: list[int]) -> dict[str, int]: ...

# ❌ Requires typing module — fails on embedded runtimes
from typing import Optional, List
def read(self, timeout: Optional[int] = None) -> Optional[bytes]: ...
```

Infrastructure code (`scripts/`, `support/`) may use `typing` imports since it runs only on CPython.

([Decision 0021](plans/decisions/0021-docstring-type-policy.md))

## Docstrings

Google-style. Types go on annotations, descriptions go in docstrings — no redundancy.

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

- **`Args:`** — `name: description` (no type in parens)
- **`Returns:`** — description only (no `type:` prefix)
- **`Raises:`** — `ExceptionType: description`

Document all public functions, methods, and classes. The docs build fails on griffe warnings about missing or malformed sections.

([Decision 0021](plans/decisions/0021-docstring-type-policy.md))

## String formatting

f-strings exclusively. No `%`-style, no `.format()`.

```python
# ✅
print(f"Found {count} items in {directory}")

# ❌
print("Found %d items in %s" % (count, directory))
print("Found {} items in {}".format(count, directory))
```

## Memory patterns (library code only)

These apply to **publishable library code under `libraries/`** — code that runs on microcontrollers. Infrastructure code (`scripts/`, `support/`) should use standard Python conventions.

| Pattern | Why |
|---|---|
| Pre-allocate `bytearray` in constructor, reuse with `readinto()` | Avoid repeated allocation |
| `memoryview` for slicing | Avoid copies |
| `const()` for numeric constants (import from `micropython`) | Compiler optimization |
| Cache frequently used attributes in local variables | Reduce attribute lookups in hot paths |
| Avoid dynamic string building in loops | GC pressure |

## What the linter checks

`python scripts/run.py lint` runs two tools:

1. **Ruff** — PEP 8 style, import sorting, common bugs (`E`, `F`, `I`, `B`, `UP` rule sets)
2. **CHU001** — naming conventions (single-letter names, banned abbreviations, banned suffixes)

If lint passes, your style is correct.

