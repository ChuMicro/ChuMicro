# Decision 0006: Shared import-free compatibility smoke runner

Status: `superseded`
Date: `2026-03-29`
Superseded by: [Decision 0016](0016-cross-runtime-unit-tests.md)

## Context

ChuMicro now verifies the same tiny timing smoke test under CPython, MicroPython unix-port, and CircuitPython unix-port. During local runtime validation, the repo hit interpreter-specific inconsistencies around executing the same checked-in smoke files through normal filesystem imports, especially in the CircuitPython unix-port path.

The repo still needs one small, repeatable compatibility signal that humans, agents, and CI can run across interpreters without introducing a larger runtime-specific harness split too early.

## Decision

Use `support/test_harness/run_device_smoke.py` as the **canonical compatibility smoke runner** for the current workspace phase.

This runner should stay:

- shared across CPython, MicroPython unix-port, and CircuitPython unix-port
- intentionally tiny
- import-free enough to execute consistently across the supported interpreters
- focused on one checked-in timing smoke behavior rather than pretending to be a full runtime test suite

## Consequences

- compatibility checks in `scripts/run.py` can use one canonical smoke path across interpreters
- the smoke runner is a verified execution path, not a claim that normal package imports are already equivalent on every runtime
- richer runtime-specific import checks can be added later without replacing this small baseline signal
- planning and docs should refer to `support/test_harness/run_device_smoke.py` as canonical

## Superseded note

The current canonical cross-runtime entrypoint is
`support/test_harness/run_cross_runtime.py` (see Decision 0016).  The
`run_device_smoke.py` path described above no longer exists; it was
folded into the broader cross-runtime test runner that also exercises
real `tests/` files via the lightweight harness.
