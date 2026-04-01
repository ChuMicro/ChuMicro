# Workstream: Sample Library

Status: `in-progress`

## Purpose

Create a small `sample` library that proves the Chumicro ecosystem rather than just describing it.

## Scope

- publishable library layout with `src/`, `tests/`, `device_tests/`, and `doc/`
- cross-runtime import and shim patterns
- host-side testability through mocks or stubs
- IDE ergonomics for downstream developers
- a small but real public API that proves cross-runtime behavior

## Current verified package shape

```text
libraries/sample/
├── VERSION
├── pyproject.toml
├── README.md
├── src/
│   └── chumicro_sample/
├── tests/
│   ├── mocks/
│   └── test_*.py
├── device_tests/
│   └── test_*.py
└── doc/
```

## Current verified slice

- `libraries/sample/src/chumicro_sample/__init__.py` exports the current public API
- `libraries/sample/src/chumicro_sample/heartbeat.py` implements the first public behavior slice
- `libraries/sample/src/chumicro_sample/ticks.py` provides the cross-runtime timing seam
- `libraries/sample/tests/` covers the host-side behavior with `pytest`
- `libraries/sample/device_tests/test_heartbeat_ticks.py` exists as the first device-aware timing test
- `libraries/sample/pyproject.toml` builds as an individual package
- `libraries/sample/README.md` and `libraries/sample/doc/` establish the package documentation shape

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

- the package root currently exports `Heartbeat`, `SystemTicks`, `TickSource`, `ticks_ms()`, and `ticks_diff()`
- the core logic is runtime-agnostic and exercised on CPython
- the timing seam is implemented without requiring a board for the main host test path

## Settled context for the first sample library

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

- `ci/tasks.py test-micropython-compat` exists as the first MicroPython compatibility entrypoint
- `ci/tasks.py prepare-micropython` exists as the repo-managed MicroPython runtime bootstrap command
- `ci/run_sample_device_smoke.py` exists as the canonical runtime-switchable smoke script, with `ci/run_sample_device_tests.py` kept as a compatibility wrapper
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

- sample library code stays small and readable
- the same public API works across CPython, MicroPython, and CircuitPython where practical
- CPython tests cover the core behavior with 90%+ coverage
- the package can be built and prepared for release independently of the rest of the repo
- at least one behavior is proven through device-aware testing, not only host mocks

## Current progress against success criteria

- the sample library remains small and readable
- the same public timing API is implemented for CPython and structured for target-runtime reuse
- host tests and coverage are already proven in this workspace
- the package already builds independently
- at least one device-aware behavior is represented by the checked-in timing test and smoke runner scaffold

Still intentionally incomplete:

- the CircuitPython compatibility path is still advisory in CI rather than a required gate
- package-root export coverage is still strongest for `Heartbeat`; the broader package-root export surface is defined but not yet exhaustively tested as a public contract
- IDE-facing stub packaging is still open
- the second seam after timing/ticks is still open

## Notes

The sample library should be intentionally small. Its job is to prove workspace conventions, not to be feature-rich.

The current implemented slice is a heartbeat-style library whose timing behavior is validated on CPython, exercised through repo-managed MicroPython and CircuitPython unix-port smoke paths, and represented by a first manual device-aware test path.

## Open decisions

- Should digital I/O become the immediate second seam, or should the next sample iteration stay focused on hardening the timing contract first?
- Should IDE-facing stubs be added before the second seam, or only after one more library slice proves the pattern?
- Once the advisory runtime compatibility jobs have soaked in CI, should they remain optional or become part of the protected-branch policy?

