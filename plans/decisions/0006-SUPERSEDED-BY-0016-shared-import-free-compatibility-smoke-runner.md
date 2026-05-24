# Decision 0006: Shared import-free compatibility smoke runner

Status: `superseded`
Date: `2026-03-29`
Summary: Used a single tiny import-free smoke runner at `support/test_harness/run_device_smoke.py` for all three runtimes during the early workspace phase.
Related: Decision 0003 (test boundaries)
Superseded by: [Decision 0016](0016-cross-runtime-unit-tests.md)

## Context

ChuMicro now verifies the same tiny timing smoke test under CPython, MicroPython unix-port, and CircuitPython unix-port. During local runtime validation, the repo hit interpreter-specific inconsistencies around executing the same checked-in smoke files through normal filesystem imports, especially in the CircuitPython unix-port path.

The repo still needs one small, repeatable compatibility signal that humans, agents, and CI can run across interpreters without introducing a larger runtime-specific harness split too early.

## Decision

Used `support/test_harness/run_device_smoke.py` as the canonical compatibility smoke runner during the early workspace phase.  The runner stayed shared across CPython, MicroPython unix-port, and CircuitPython unix-port, intentionally tiny, and import-free enough to execute consistently — focused on one checked-in timing smoke behavior rather than pretending to be a full runtime test suite.

## Consequences

- Compatibility checks in `scripts/run.py` used one canonical smoke path across interpreters.
- The smoke runner was a verified execution path, not a claim that normal package imports were already equivalent on every runtime.
- Replaced by the broader cross-runtime test runner ([Decision 0016](0016-cross-runtime-unit-tests.md)).  Current entrypoint: `support/test_harness/run_cross_runtime.py`; `run_device_smoke.py` no longer exists.
