# Workstream: Timing Library

Status: `in-progress`

## Purpose

Create the `chumicro-timing` library — cross-runtime tick helpers and periodic timing utilities.

## Scope

- publishable library layout under `libraries/timing/` with `src/`, `tests/`, and `device_tests/`
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
└── device_tests/
    └── test_*.py
```

## Current verified slice

- `libraries/timing/src/chumicro_timing/__init__.py` exports the current public API
- `libraries/timing/src/chumicro_timing/heartbeat.py` implements the first public behavior slice
- `libraries/timing/src/chumicro_timing/ticks.py` provides the cross-runtime timing seam
- `libraries/timing/tests/` covers the host-side behavior with `pytest`
- `libraries/timing/device_tests/test_heartbeat_ticks.py` exists as the first device-aware timing test
- `libraries/timing/pyproject.toml` builds as an individual package
- `libraries/timing/README.md` establishes the package documentation

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
- `ci/run_sample_device_smoke.py` exists as the canonical runtime-switchable smoke script
- the MicroPython path has been exercised successfully in this workspace with the repo-managed local Unix-port runtime and now runs as an advisory CI job
- the CircuitPython path has been exercised successfully in this workspace with the repo-managed local Unix-port runtime and now runs as an advisory CI job
- per [Decision 0006](../decisions/0006-shared-import-free-compatibility-smoke-runner.md), the canonical smoke path stays intentionally import-free for the current workspace phase

These checks should not be treated as proof of full board behavior yet.

### `device_tests/`

Current verified state:

- `device_tests/` exists for runtime-specific behavior that host mocks cannot fully prove
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
- at least one device-aware behavior is represented by the checked-in timing test and smoke runner scaffold

Still intentionally incomplete:

- the CircuitPython compatibility path is still advisory in CI rather than a required gate
- package-root export coverage is still strongest for `Heartbeat`; the broader package-root export surface is defined but not yet exhaustively tested as a public contract
- the second seam after timing/ticks is still open

## Notes

The timing library should remain small and focused. Its job is to provide a correct, cross-runtime timing foundation.

The current implemented slice is a heartbeat-style utility whose timing behavior is validated on CPython, exercised through repo-managed MicroPython and CircuitPython unix-port smoke paths, and represented by a first manual device-aware test path.

## Resolved decisions

- **Second seam:** Digital I/O will become the second seam, but the priority is to explore CI and release more deeply with just the timing library (and possibly one more) before adding many libraries. Both tracks proceed in parallel.
- **IDE-facing stubs:** Prove out IDE stub packaging now, before the second seam. This is part of the timing library's remaining exit criteria.
- **Advisory runtime compat jobs:** These should become mandatory protected-branch requirements eventually. They will be gated by platform targeting (Decision 0011) so that only libraries declaring support for MicroPython/CircuitPython are required to pass those checks.

