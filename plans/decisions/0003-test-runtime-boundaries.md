# Decision 0003: Test and runtime boundaries

Status: `accepted`
Date: `2026-03-28`
Related: Decision 0010 (testability), Decision 0016 (cross-runtime unit tests), Decision 0027 (device tests)

## Context

Most development and CI must happen on CPython, but the libraries ultimately target MicroPython and CircuitPython semantics on constrained hardware.

## Decision

Use CPython-hosted tests as the default path, prefer simulation or emulation where practical, and reserve real-device execution for explicit workflows and local testbed setups.

The working test pyramid is:

- required: CPython-hosted `pytest` tests with coverage
- required: cross-runtime unit tests on MicroPython and CircuitPython unix-ports via the `chumicro-pytest-device` plugin's `UnixPortBackend` (see [Decision 0016](0016-cross-runtime-unit-tests.md))
- targeted: real-device `functional_tests/` run through the same plugin's `DeviceBackend` — transport layer, `devices.yml` schema, and IDE integration defined in [Decision 0027](0027-device-testing-infrastructure.md)

## Consequences

- packages should be designed for dependency injection and host-side mocks
- cross-runtime unit tests run on unix-ports using plain asserts and constructor-injected fakes (Decision 0016)
- real-device workflows remain important but should stay opt-in until stable
- `pytest` remains the primary host framework, but it is not assumed to run directly on constrained boards
