# IDE Type Stubs

This directory provides `.pyi` stub files for CircuitPython and MicroPython modules so that IDEs (PyCharm, VS Code/Pyright) can resolve platform-specific imports without red squigglies.

## How it works

- **Pyright / VS Code / Pylance:** `typings/` is Pyright's default `stubPath` — auto-discovered, zero config.
- **PyCharm:** `typings/` is registered as a source root by `scripts/run.py sync-ide`.

## What belongs here

Only stubs for modules that **don't exist on CPython** but are imported by Chumicro libraries. Each stub should cover the minimum API surface the codebase actually uses.

Do not stub standard library modules or CPython packages — those already have types.

## Adding a new stub

1. Create `typings/<module_name>/__init__.pyi` (or `typings/<module_name>.pyi` for flat modules).
2. Define only the functions, classes, and constants that Chumicro code imports.
3. Run `python scripts/run.py sync-ide` (not strictly needed — Pyright finds it automatically and PyCharm config already includes `typings/`).
4. Verify in your IDE that the import resolves.

## Upgrade path

If the number of stubs grows large, consider extracting specific modules from upstream stub packages (`circuitpython-stubs`, `micropython-stubs`) into this directory via a `sync-stubs` task. The `typings/` layout is the standard Pyright convention and is compatible with vendored upstream stubs.

