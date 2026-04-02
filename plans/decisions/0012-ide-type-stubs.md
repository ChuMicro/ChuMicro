# Decision 0012 — IDE type stubs for platform-specific modules

Status: `accepted`

## Context

Chumicro libraries import modules that only exist on CircuitPython or MicroPython (e.g., `micropython.const`, `supervisor.ticks_ms`).  The code uses `try/except ImportError` guards so it runs correctly on CPython, but IDEs still flag the imports as unresolved — red squigglies in PyCharm, yellow warnings in VS Code/Pyright.

The workspace constraint "no pip-installed dev packages for IDE resolution" (see workspace-history.prompt.md) rules out `pip install circuitpython-stubs`.

## Decision

Hand-write minimal `.pyi` stub files in a `typings/` directory at the repo root.  Only stub the API surface that Chumicro code actually imports.

### Why `typings/`

- Pyright auto-discovers `typings/` as its default `stubPath` — zero configuration.
- PyCharm resolves stubs when `typings/` is registered as a source root by `sync-ide`.
- The name is the standard Pyright convention, so contributors familiar with the ecosystem expect it.

### What belongs in `typings/`

Only stubs for modules that do not exist on CPython but are imported by Chumicro libraries.  Each stub covers the minimum API surface the codebase uses.  Standard library and CPython package stubs do not belong here.

### Current stubs

- `typings/micropython/__init__.pyi` — `const()`
- `typings/supervisor/__init__.pyi` — `ticks_ms()`

### Adding new stubs

When a new library imports a platform-specific module (e.g., `board`, `digitalio`, `machine`), add a stub with only the used symbols.  Run `sync-ide` if PyCharm hasn't picked it up (though `typings/` is already a source root).

## Consequences

- IDE squigglies for platform-specific imports are eliminated.
- No pip-installed stub packages needed.
- Stubs grow incrementally as libraries add platform-specific imports.
- If the surface area ever gets large, a `sync-stubs` task can extract modules from upstream stub packages (`circuitpython-stubs`, `micropython-stubs`) into the same `typings/` layout.

