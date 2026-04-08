# 0021 — Docstring Type Policy

**Status:** accepted
**Date:** 2026-04-07
**Revised:** 2026-04-08

## Context

CircuitPython and MicroPython do not reliably support Python type
annotations on function signatures.  Some runtimes ignore them, others
raise errors, and annotations consume heap RAM that embedded boards
cannot spare.  The project still needs type information for
documentation generation (griffe / mkdocstrings), IDE code hints, and
developer readability.

## Decision

1. **Document types in Google-style docstrings**, not function
   annotations.  The format differs by section — this follows the
   [standard Google-style convention][google-style]:

   - **`Args:`** — `param_name (type): description`
   - **`Returns:`** — `type: description` (no name, just the type)
   - **`Raises:`** — `ExceptionType: description`
   - **`Attributes:`** — `attr_name (type): description`

   The `Returns:` section is the one most people get wrong.  Standard
   Google-style does **not** put a name before the type in Returns.

   ```python
   # ✅ Correct
   def ticks_diff(end, start):
       """Signed difference between two tick values.

       Args:
           end (int): Later tick value.
           start (int): Earlier tick value.

       Returns:
           int: Signed difference in milliseconds.
       """

   # ❌ Wrong — do not name the return value
   #     Returns:
   #         result (int): Signed difference in milliseconds.
   ```

2. **Do not add Python type annotations** (`: int`, `-> bool`) to
   function or method signatures in library code under `libraries/`.

3. **Infrastructure code** (`scripts/`, `support/`) may use either
   docstring types or function annotations since it runs only on
   CPython.  Prefer docstring types for consistency unless a tool
   requires annotations.

4. **Pin `docstring_style: google`** and
   **`docstring_options: { returns_named_value: false }`** in every
   library's `mkdocs.yml` under
   `plugins.mkdocstrings.handlers.python.options` so griffe parses
   the standard `type: description` Returns format correctly.

5. **Enforce zero griffe warnings** in the `docs` task and in
   `preflight`.  The docs build captures stderr and fails if griffe
   reports any warnings about missing or malformed docstring sections.

[google-style]: https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings

## Consequences

- All public functions, methods, and classes in library code must
  have Google-style docstrings with typed `Args:` / `Returns:` /
  `Raises:` sections.
- griffe warnings become CI-blocking, catching docstring regressions
  before merge.
- The `testing.py` submodules (which also ship in library packages)
  may use function annotations because `FakeTicks` already does.
  This is acceptable — `testing.py` is only imported on CPython
  during test runs, never on embedded boards.  However, docstring
  types are still preferred for consistency.

