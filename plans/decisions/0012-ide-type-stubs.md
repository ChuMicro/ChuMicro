# Decision 0012 — IDE type stubs for platform-specific modules

Status: `accepted`
Date: `2026-04-02`
Related: Decision 0007 (cross-platform deps — §3 prefigures this)

## Context

ChuMicro libraries import modules that only exist on CircuitPython or MicroPython (e.g., `micropython.const`, `supervisor.ticks_ms`, `machine.Pin`).  The code uses `try/except ImportError` guards so it runs correctly on CPython, but IDEs flag the imports as unresolved.

Hand-written `.pyi` stubs in a `typings/` directory were considered and rejected — well-maintained upstream stub packages exist for both runtimes.

## Decision

Install **two upstream stub packages**, version-pinned to match the runtime versions in `target-runtimes.toml`:

- **`circuitpython-stubs`** — covers all CircuitPython built-in modules (`supervisor`, `board`, `digitalio`, `micropython`, etc.).  Published by Adafruit, PEP 561 compliant.
- **`micropython-esp32-stubs`** — covers MicroPython-only modules (`machine`, `network`, `esp`, `esp32`, `btree`, `framebuf`, `uctypes`, etc.).  Published by the micropython-stubber project, auto-generated from real ESP32 hardware.

### Why PyPI rather than building stubs from source

CircuitPython's tree includes `tools/extract_pyi.py` which extracts `.pyi` stubs from `//|` comment lines in C source.  Running it requires `isort`, `black`, and `circuitpython_typing`.  The output is byte-for-byte identical to what Adafruit publishes from the same release tag.  MicroPython has no in-repo stub infrastructure at all.  Both upstream packages are the right answer — no need to build our own.

### How version sync is maintained

`target-runtimes.toml` at the repo root is the single source of truth for pinned runtime versions.  `setup()` in `scripts/run.py` reads both versions and pins:

- `circuitpython-stubs=={cp_version}` (exact match)
- `micropython-esp32-stubs=={mp_version}.*` (allows post-releases)

The same file is read by `scripts/shared.py` for cloning.  Changing the version in one place updates stubs, cloned repos, and built binaries on the next `setup` run.

### Coverage and coexistence

The two packages use different PEP 561 layouts and coexist cleanly:

- `circuitpython-stubs` installs as `-stubs` directories (e.g., `supervisor-stubs/__init__.pyi`)
- `micropython-esp32-stubs` installs as flat `.pyi` files (e.g., `machine.pyi`)

Together they cover:
- **CircuitPython-only**: `supervisor`, `board`, `digitalio`, `analogio`, `busio`, `neopixel_write`, `wifi`, `socketpool`, `storage`, `microcontroller`, `countio`, `keypad`, `pulseio`, `pwmio`, `rtc`, etc.
- **MicroPython-only**: `machine` (Pin, I2C, SPI, UART, PWM, ADC, Timer, WDT, RTC, SDCard), `network` (WLAN, LAN, PPP), `esp`, `esp32`, `espnow`, `btree`, `cryptolib`, `deflate`, `framebuf`, `uctypes`, `vfs`, etc.
- **Shared**: `micropython` (see conflict note below)

### Known conflict: `micropython` module

Both packages define stubs for the `micropython` module.  CircuitPython stubs provide `micropython-stubs/__init__.pyi` (PEP 561 `-stubs` directory, only `const()`).  MicroPython stubs provide `micropython.pyi` (flat file, 350 lines with `const`, `mem_info`, `schedule`, `heap_lock`, `opt_level`, etc.).

Per PEP 561, the `-stubs` package has higher precedence, so type checkers resolve `micropython` to the CircuitPython stub.  This means the richer MicroPython `micropython` module stubs are shadowed.

**Current impact**: None — our code only uses `micropython.const()`, which both stubs define.

**Future mitigation** (when needed): If a library needs `micropython.schedule()` or other MP-only APIs, we can override the resolution by placing a merged stub in a `typings/micropython/` directory and adding it to the type checker's search path.  This is a targeted fix for one module, not a return to hand-writing all stubs.

### Installation

Both packages are installed by `python scripts/run.py setup` alongside other dev dependencies.

## Consequences

- IDE squigglies for platform-specific imports are eliminated for both runtimes.
- No hand-written stubs to maintain.
- Stubs stay in sync with pinned runtime versions automatically via `target-runtimes.toml`.
- Two additional PyPI dependencies in the dev environment.
- The `micropython` module conflict is documented and has a clear mitigation path.
