# Decision 0003: Test and runtime boundaries

Status: `accepted`
Date: `2026-03-28`

## Context

Most development and CI must happen on CPython, but the libraries ultimately target MicroPython and CircuitPython semantics on constrained hardware.

## Decision

Use CPython-hosted tests as the default path, prefer simulation or emulation where practical, and reserve real-device execution for explicit workflows and local testbed setups.

The working test pyramid is:

- required: CPython-hosted `pytest` tests with coverage
- preferred when realistic: compatibility smoke tests or emulation for MicroPython and CircuitPython
- targeted: real-device `device_tests/` run through a small Chumicro harness

## Consequences

- packages should be designed for dependency injection and host-side mocks
- simulation/emulation should be added before mandatory hardware gates
- real-device workflows remain important but should stay opt-in until stable
- `pytest` remains the primary host framework, but it is not assumed to run directly on constrained boards

