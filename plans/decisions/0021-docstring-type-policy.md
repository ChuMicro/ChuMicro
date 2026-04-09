# 0021 — Type Documentation Policy

**Status:** accepted
**Date:** 2026-04-07
**Revised:** 2026-04-08

## Context

Python type annotations work correctly on both CircuitPython (10.1.4)
and MicroPython (v1.26.0) — all annotation syntax is parsed without
error and functions execute normally.  Both runtimes silently discard
`__annotations__`, so runtime introspection is not available, but the
annotations are visible in source code, to IDEs, and to documentation
tools (griffe / mkdocstrings).

The `typing` module (`Optional`, `Union`, `List`, `Dict`, `Callable`,
`Any`, `TYPE_CHECKING`) does **not** exist on either embedded runtime.
`from __future__ import annotations` is also unavailable.  However,
PEP 604 (`int | None`) and PEP 585 (`list[int]`, `dict[str, int]`)
both work, covering the most common use cases that previously required
`typing` imports.

Memory overhead is ~30 bytes per annotated function — negligible.

## Decision

1. **Use standard Python type annotations** on function and method
   signatures in all code (library, infrastructure, tests).

2. **Do not import `typing`** in library code under `libraries/`.
   The module does not exist on CircuitPython or MicroPython.  Use
   PEP 604 and PEP 585 syntax instead:

   ```python
   # ✅ Works on all runtimes
   def read(self, timeout: int | None = None) -> bytes | None: ...
   def process(self, items: list[int]) -> dict[str, int]: ...

   # ❌ Requires typing module — fails on embedded runtimes
   from typing import Optional, List, Dict
   def read(self, timeout: Optional[int] = None) -> Optional[bytes]: ...
   ```

3. **Write Google-style docstrings for descriptions.**  Since types
   are on the signature, docstrings carry descriptions only:

   - **`Args:`** — `param_name: description` (no type in parens)
   - **`Returns:`** — description only (no `type:` prefix)
   - **`Raises:`** — `ExceptionType: description` (unchanged)
   - **`Attributes:`** — `attr_name: description` (no type in parens)

   ```python
   # ✅ Correct — annotations carry types, docstrings carry descriptions
   def ticks_diff(end: int, start: int) -> int:
       """Signed difference between two tick values.

       Args:
           end: Later tick value.
           start: Earlier tick value.

       Returns:
           Signed difference in milliseconds.
       """
   ```

4. **Pin `docstring_style: google`** in every library's `mkdocs.yml`
   under `plugins.mkdocstrings.handlers.python.options`.  The
   `returns_named_value: false` option is no longer needed when
   types are on annotations (griffe reads them from the signature).

5. **Enforce zero griffe warnings** in the `docs` task and in
   `preflight`.  The docs build captures stderr and fails if griffe
   reports any warnings about missing or malformed docstring sections.

6. **Infrastructure code** (`scripts/`, `support/`) may additionally
   use `typing` imports since it runs only on CPython.

[google-style]: https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings

## Consequences

- All public functions, methods, and classes should have type
  annotations on their signatures and Google-style docstrings with
  description-only `Args:` / `Returns:` / `Raises:` sections.
- griffe extracts types from annotations and descriptions from
  docstrings — no redundancy needed.
- The `typing` module constraint is the only embedded-specific rule.
  Everything else follows standard Python conventions.
- Existing library code uses the old docstring-types-only style.
  Migration to annotations will happen incrementally as libraries
  are touched.
