# Decision 0012 — IDE type stubs for platform-specific modules

Status: `accepted` (revised)

## Context

Chumicro libraries import modules that only exist on CircuitPython or MicroPython (e.g., `micropython.const`, `supervisor.ticks_ms`).  The code uses `try/except ImportError` guards so it runs correctly on CPython, but IDEs flag the imports as unresolved.

An earlier draft hand-wrote minimal `.pyi` stubs in a `typings/` directory.  This was revised: Adafruit publishes `circuitpython-stubs` on PyPI, built from the same tagged source tree we already clone.

## Decision

Install **`circuitpython-stubs`** from PyPI, version-pinned to match `CIRCUITPYTHON_RELEASE` in `ci/prepare_circuitpython.py`.

### Why PyPI rather than building stubs from the cloned repo

The CircuitPython tree includes `tools/extract_pyi.py`, which extracts `.pyi` stubs from `//|` comment lines in C source under `shared-bindings/`.  Running it requires `isort`, `black`, and `circuitpython_typing` as build-time dependencies.  The output is byte-for-byte identical to what Adafruit publishes to PyPI from the same release tag.  Building from source would add three dependencies and a new build step for zero benefit.

### How version sync is maintained

`setup()` in `scripts/run.py` reads `CIRCUITPYTHON_RELEASE` from `ci/prepare_circuitpython.py` and pins the stubs install to `circuitpython-stubs=={version}`.  The version is defined in exactly one place; changing the pinned CircuitPython tag automatically changes the stubs version on the next `setup` run.

### Coverage

`circuitpython-stubs` is PEP 561 compliant and provides stubs for all CircuitPython built-in modules, including `micropython` (with `const()`), `supervisor` (with `ticks_ms()`), `board`, `digitalio`, etc.  Both Pyright and PyCharm auto-discover PEP 561 stubs from installed packages — no IDE configuration changes are needed.

### MicroPython-only stubs

`circuitpython-stubs` already covers the `micropython` module APIs shared between both runtimes (e.g., `const()`).  MicroPython-specific modules like `machine`, `network`, `esp`, and `esp32` are not needed yet.  When a library first imports one, two options will be evaluated:

1. **`micropython-esp32-stubs`** from PyPI (from the micropython-stubber project) — auto-generated, versioned per MicroPython release.
2. **Introspect from the built unix port** — run the MicroPython binary we already build, enumerate modules via `dir()`, emit `.pyi` files.  This is what micropython-stubber does internally; building our own version is a significant tooling investment.

Both options will be evaluated at the point of need, not speculatively.

### Installation

`circuitpython-stubs` is installed by `python scripts/run.py setup` alongside other dev dependencies.

## Consequences

- IDE squigglies for platform-specific imports are eliminated.
- No hand-written stubs to maintain.
- Stubs stay in sync with the cloned CircuitPython version automatically.
- One additional PyPI dependency in the dev environment.

## Supersedes

This revision replaces the original `typings/` approach.  The `typings/` directory has been removed and `sync-ide` no longer references it.
