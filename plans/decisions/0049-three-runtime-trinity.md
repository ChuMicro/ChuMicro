# Decision 0049: Three runtimes — CPython is the testing seam, not a deployment target

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0003 (test boundaries), Decision 0011 (per-library platform targeting), Decision 0016 (cross-runtime unit tests), Decision 0010 (testability + `testing.py` fakes), Decision 0037 (runtime file marking).

## Context

ChuMicro was built ground-up to target CircuitPython, MicroPython, and CPython.  The trinity is in the project's identity (README, CONTRIBUTING.md, AGENTS.md) and every cross-cutting decision (per-library platforms key, cross-runtime test runner, runtime-marker filter, workbench-vs-libraries split, bundle-vs-PyPI distribution model) assumes it.

What hadn't been written down is *why* CPython is in the set — the role it plays is conceptually different from CP and MP.  CP and MP are deployment targets (the runtime that runs on a board); CPython is not.  Without naming the role explicitly, several adjacent decisions (the `_adapters/cpython.py` pattern, `testing.py` fakes shipping only in PyPI sdists, workbench packages being CPython-only) read as accidental rather than load-bearing.

## Decision

ChuMicro targets exactly three runtimes, each with a distinct role:

- **CircuitPython** and **MicroPython** are **deployment runtimes** — application code runs on a microcontroller under one of them.
- **CPython** is the **host-test seam** — where unit tests run, where fakes execute, where every workbench tool runs, where AI agents and contributors iterate.  Application authors install libraries via `pip install chumicro-foo` on a CPython host even when their final target is a board (the host CPython side is what enables testing, fakes, and editor support to work without a device plugged in).

The trinity is what enables the rest of the architecture:

- **`[tool.chumicro].platforms`** (Decision 0011) marks per-library runtime support against this exact three-value vocabulary.
- **`__chumicro_runtimes__`** module markers (Decision 0037) filter files into per-runtime bundles using the same vocabulary.
- **`testing.py`** fakes (Decision 0010) are CPython-only modules that ship with every library so downstream test suites can import them without monkey-patching.
- **The `_adapters/cpython.py` pattern** in I/O libraries (sockets, wifi, kvstore) lets a host-side test connect to real network resources and still exercise the same protocol surface that runs on a board.
- **`libraries/` vs `workbench/`** (Decision 0032) is the destination split — multi-runtime libraries to the device, CPython-only host tools to the laptop.

## Rejected

**MP + CP only, stub-driven CI.**  Without CPython, host-side tests would need stubs for every CP/MP-specific module, hand-maintained as the runtimes evolve.  Application authors couldn't `pip install chumicro-foo` from a CPython host — they'd be forced to lay out their app in a workspace, deploy to a device, and run tests on hardware to get any feedback at all.  Inner-loop story collapses.

**CPython only.**  No embedded story; project loses its reason to exist.

**Add a fourth runtime (Pyodide, MicroPython unix-port as a separate slot, Brython).**  Net new file-routing complexity for marginal value.  MicroPython's unix-port is treated as MP for file-routing purposes — it runs cross-runtime tests but isn't a separate deployment target (Decision 0015's hardware tiers don't include it).  If a fourth meaningfully-different runtime later qualifies (a new Python implementation that ships on a different class of board), this decision gets revisited.

## Consequences

- Every device library must be import-safe on CPython — no top-level imports of `wifi`, `machine`, `microcontroller`.  Use try/except guards or `_select_adapter` patterns.
- Every library that owns I/O ships an `_adapters/cpython.py` (often a real-stdlib implementation, not a fake) so host-side tests exercise the protocol against a real backend where reasonable.
- `testing.py` always declares `__chumicro_runtimes__ = ("cpython",)` so the bundle pipeline keeps it off devices but PyPI sdists still ship it.
- pyproject.toml `[project].dependencies` lists CPython-installable packages.  CP/MP install dependencies through their own channels (mip / circup); the bundle pipeline enforces no-cross-runtime-dep-leakage.
- A workbench package proposing to depend on a chumicro library must still respect Decision 0052 — the trinity gives workbench tools access to a CPython library's surface, but the import boundary remains.
