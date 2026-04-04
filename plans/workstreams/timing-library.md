# Workstream: Timing Library

Status: `done`

## Purpose

Create the `chumicro-timing` library — cross-runtime tick helpers and periodic timing utilities.

## Scope

- publishable library layout under `libraries/timing/` with `src/`, `tests/`, and `functional_tests/`
- cross-runtime import and shim patterns
- host-side testability through mocks or stubs
- IDE ergonomics for downstream developers
- a small but real public API that proves cross-runtime behavior

## Current verified package shape

```text
libraries/timing/
├── VERSION
├── pyproject.toml
├── README.md
├── src/
│   └── chumicro_timing/
├── tests/
│   └── test_*.py
├── functional_tests/
│   └── test_*.py
├── docs/
│   ├── guide.md
│   ├── api.md
│   └── testing.md
└── examples/
    ├── heartbeat_blink.py
    ├── multiple_heartbeats.py
    └── timeout_check.py
```

## Current verified slice

- `libraries/timing/src/chumicro_timing/__init__.py` exports the current public API
- `libraries/timing/src/chumicro_timing/heartbeat.py` implements the `Heartbeat` class with `poll(now_ms)`, `is_due(now_ms)`, and `reset(now_ms)` — all requiring a shared timestamp (Decision 0014)
- `libraries/timing/src/chumicro_timing/ticks.py` provides the cross-runtime timing seam
- `libraries/timing/tests/` covers the host-side behavior with `pytest`
- `libraries/timing/functional_tests/test_heartbeat_ticks.py` exists as the first device-aware timing test
- `libraries/timing/pyproject.toml` builds as an individual package
- `libraries/timing/README.md` establishes the package documentation with installation, API overview, and platform notes
- `libraries/timing/docs/` contains user guide, API reference, and testing helpers documentation (Decision 0013)
- `libraries/timing/examples/` contains three runnable examples: heartbeat blink, multiple heartbeats, and timeout check (Decision 0013)
- current version: `0.1.0` (pre-release; nothing published yet)

## Design rules

- keep the public API tiny
- keep most logic runtime-agnostic
- isolate platform-specific behavior behind one shim or adapter boundary
- prefer constructor injection over global imports for hardware-facing dependencies
- do not require a board just to validate the core behavior

## Selected first shape

Chosen direction: **Option B** — mostly pure logic plus one small hardware-facing seam.

Chosen first seam: **timing / ticks**.

Immediate follow-up seam after the timing proof: **digital I/O**.

Current verified implementation:

- the package root currently exports `Heartbeat`, `ticks_ms()`, `ticks_diff()`, and `ticks_add()`
- the core logic is runtime-agnostic and exercised on CPython
- the timing seam is implemented without requiring a board for the main host test path

## Settled context for the first timing library

### Option A: pure logic plus runtime detection

Pros:

- lowest risk
- fastest to implement
- easiest CI story

Cons:

- weak proof that the workspace really supports embedded use cases

### Option B: logic plus one small hardware-facing shim

Example shape:

- small service object with a pure-Python state machine
- one adapter for a board-facing capability such as digital output, timer ticks, or simple stream I/O

Pros:

- better proof of real cross-runtime design
- forces mock and on-device strategy to be real early

Cons:

- more moving parts in the first milestone

This section is retained as historical context for why Option B was chosen. The repo has already implemented the Option B timing-first slice.

## Current testing matrix

### CPython `tests/`

Current verified state:

- `pytest` is the active host-side test framework
- host tests cover `Heartbeat` behavior, package-root `Heartbeat` import behavior, and timing-shim behavior
- the current host test run exceeds the 90% coverage gate

### Compatibility checks

Current verified state:

- `scripts/run.py test-micropython-compat` exists as the first MicroPython compatibility entrypoint
- `scripts/run.py prepare-micropython` exists as the repo-managed MicroPython runtime bootstrap command
- `support/test_harness/run_cross_runtime.py` exists as the canonical cross-runtime test runner
- the MicroPython path has been exercised successfully in this workspace with the repo-managed local Unix-port runtime and now runs as an advisory CI job
- the CircuitPython path has been exercised successfully in this workspace with the repo-managed local Unix-port runtime and now runs as an advisory CI job
- per [Decision 0016](../decisions/0016-cross-runtime-unit-tests.md), the compat tasks run real unit tests from `tests/` through the lightweight harness, skipping pytest-only files automatically

These checks should not be treated as proof of full board behavior yet.

### `functional_tests/`

Current verified state:

- `functional_tests/` exists for runtime-specific behavior that host mocks cannot fully prove
- `support/test_harness/` is the current tiny runner for this layer
- real-board execution is still manual-only

`pytest` should remain the host framework, but not the direct board runtime dependency.

## Success criteria

- timing library code stays small and readable
- the same public API works across CPython, MicroPython, and CircuitPython where practical
- CPython tests cover the core behavior with 90%+ coverage
- the package can be built and prepared for release independently of the rest of the repo
- at least one behavior is proven through device-aware testing, not only host mocks

## Current progress against success criteria

- the timing library remains small and readable
- the same public timing API is implemented for CPython and structured for target-runtime reuse
- host tests and coverage are already proven in this workspace
- the package already builds independently
- at least one device-aware behavior is represented by the checked-in timing test and cross-runtime test runner scaffold

All success criteria are met. Remaining cross-cutting items (CI promotion, release automation, second seam) are tracked under Milestone 2 and `next-up.md`.

## Notes

The timing library should remain small and focused. Its job is to provide a correct, cross-runtime timing foundation.

The current implemented slice is a heartbeat-style utility whose timing behavior is validated on CPython, exercised through repo-managed MicroPython and CircuitPython unix-port cross-runtime test paths, and represented by a first manual device-aware test path.

## Resolved decisions

- **Second seam:** Digital I/O will become the second seam, but the priority is to explore CI and release more deeply with just the timing library (and possibly one more) before adding many libraries. Both tracks proceed in parallel.
- **IDE-facing stubs:** Prove out IDE stub packaging now, before the second seam. This is part of the timing library's remaining exit criteria.
- **Advisory runtime compat jobs:** These should become mandatory protected-branch requirements eventually. They will be gated by platform targeting (Decision 0011) so that only libraries declaring support for MicroPython/CircuitPython are required to pass those checks.
- **Shared-timestamp pattern:** `Heartbeat.poll(now_ms)`, `is_due(now_ms)`, and `reset(now_ms)` require a shared timestamp (Decision 0014).  Heartbeat is a passive component checked via `poll()`.  Active components implement `service(now_ms) -> bool` (Decision 0014).
