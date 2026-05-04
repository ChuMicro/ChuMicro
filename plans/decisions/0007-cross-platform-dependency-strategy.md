# Decision 0007: Cross-platform dependency and distribution strategy

Status: `accepted`
Date: `2026-04-01`
Related: Decision 0011 (platform targeting), Decision 0012 (IDE type stubs), Decision 0018 (distribution channels)

## Context

ChuMicro targets three runtimes with three different package managers:

| Runtime        | Package manager | Default index        |
|----------------|-----------------|----------------------|
| CPython        | pip             | PyPI                 |
| MicroPython    | mip / mpremote  | micropython-lib      |
| CircuitPython  | circup          | Adafruit Bundle / Community Bundle |

The sample library's tick helpers overlap with Adafruit's `adafruit_ticks` library (MIT-licensed). Evaluating whether to depend on it or re-implement surfaced broader questions about how ChuMicro should handle external dependencies and distribute its own packages across all three ecosystems.

Key findings from the evaluation:

- `adafruit_ticks` on PyPI depends on **Adafruit-Blinka**, a heavy CircuitPython-on-Linux shim. Unacceptable as a transitive dependency for a lightweight timing library.
- `adafruit_ticks` is **not in `micropython-lib`**, so `mip` cannot install it from the default index.
- MicroPython provides `time.ticks_ms`, `time.ticks_diff`, and `time.ticks_add` as built-in functions, making a Python-level ticks library unnecessary on that runtime — but ChuMicro still needs a consistent cross-runtime API.
- Adafruit libraries on PyPI almost universally list Adafruit-Blinka as a dependency, making them impractical as lean CPython dependencies.
- The `adafruit_ticks` algorithm (ring arithmetic with a 2^29 period) is standard modular arithmetic also implemented natively in MicroPython's C runtime. It is not novel copyrightable expression.

## Decision

### 1. Re-implement rather than depend when a library fails the cross-platform test

A dependency is acceptable only when it meets **all** of these criteria:

- Available on all three target runtimes (or only needed on a subset, with a clean fallback).
- Does not pull in heavy transitive dependencies (Blinka, etc.) on any platform.
- Published through the relevant package manager for each target runtime, or trivially bundleable.

When a dependency fails any criterion, choose from the following strategies in preference order:

1. **Per-platform adapter** (preferred when the capability exists on each platform under different packages or built-ins). Write a thin adapter layer that imports the right backend per runtime. Each platform's published package declares only the dependency relevant to that platform — e.g., an Adafruit library for circup, a micropython-lib package for mip, and a PyPI package for pip. The adapter unifies the API so application code never sees the difference. Unit tests must install or mock all backends so every adapter path is exercised on the CPython host.

2. **Re-implement** (preferred for small, self-contained functionality — or when legality, licensing, or dependency weight makes adapting impractical). Write fresh code from the specification or algorithm description. Credit the upstream design in a comment when the algorithm originates from an identifiable source, but do not copy verbatim. Re-implementation is usually the better choice for small utilities (like tick arithmetic) where the adaptation overhead would exceed the implementation itself.

3. **Single cross-platform dependency** (when one package genuinely passes the three-criterion test above). Use it directly with no adapter.

The adapter approach is especially valuable for larger libraries where re-implementation carries real correctness or maintenance risk. It does require managing per-platform dependency metadata and ensuring test coverage across all adapter paths.

### 2. Publish ChuMicro packages to all three distribution channels

Each publishable library should eventually support:

- **PyPI** — standard `pyproject.toml` + `python -m build` + upload.
- **mip** — a `package.json` in the library's distribution root for `mip.install("github:org/repo/...")` or a custom index.
- **circup** — inclusion in the Community Bundle or a self-hosted circup-compatible index.

Per-platform dependency metadata is declared separately in each channel's format. A library may have different (or no) dependencies depending on the runtime.

### 3. IDE completions come from type stubs, not runtime shim packages

For CircuitPython-specific modules (`supervisor`, `board`, `digitalio`, etc.):

- Install `circuitpython-stubs` from PyPI (`pip install circuitpython-stubs`). These are `.pyi`-only packages with no runtime code and no Blinka dependency.
- For MicroPython builtins, `micropython-stubs` packages serve the same purpose.

Blinka is **not required** for IDE completions. Stubs give the IDE type information; the library's `try/except ImportError` patterns handle runtime behavior.

If ChuMicro code is written with proper feature detection (`getattr`, `try/except ImportError`), it runs correctly on CPython without any stubs. Stubs only suppress IDE warnings for platform-specific imports.

### 4. External dependencies are not banned

ChuMicro is not locked into zero-dependency mode. When an external library passes the cross-platform test above, use it. The bar is intentionally high because each dependency adds flash usage, maintenance burden, and cross-ecosystem packaging complexity — but it is not absolute.

## Consequences

- Core utilities (ticks, runtime detection) are owned by ChuMicro with no external dependencies.
- Each library must eventually carry per-platform distribution metadata (pyproject.toml, package.json, circup requirements).
- The release workstream should include tooling to publish to all three channels.
- Blinka remains useful as a development-time reference or for running CircuitPython code on Linux SBCs, but it is never a ChuMicro runtime dependency.
- When evaluating a new external dependency, apply the three-criterion test from this decision before adding it.
