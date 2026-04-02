# Workstream: Device Validation

Status: `in-progress`

## Purpose

Add a simulation-first validation path, then layer on optional hardware execution against a user-managed home testbed.

## Scope

- emulation and simulation options for CI
- local device registry and templates
- optional workflow integration for real devices
- on-device test harness planning
- transport and execution mechanics for board runs

## Current verified slice

- `support/test_harness/` exists as the current lightweight on-device runner
- `libraries/timing/device_tests/test_heartbeat_ticks.py` exists as the first device-facing timing test
- `ci/prepare_micropython.py` exists as a repo-managed MicroPython unix-port preparation path
- `ci/prepare_circuitpython.py` exists as a repo-managed CircuitPython unix-port preparation path
- `ci/run_sample_device_smoke.py` exists as the canonical checked-in smoke runner entrypoint
- `devices.example.yml` exists as the first committed local board registry template
- manual-only hardware execution is the current documented starting point

## Validation layers

### Layer 1: host-side mocks

Purpose:

- fast feedback
- high coverage for logic
- no board dependency

### Layer 2: compatibility smoke tests

Purpose:

- confirm target-runtime imports and basic semantics
- catch platform-specific module mistakes earlier than device runs

Candidate approaches:

- MicroPython Unix port where it is helpful
- CircuitPython unix port evaluation where practical, because the upstream repository does contain `ports/unix/`, but local buildability and feature parity still need to be proven for this workspace
- CPython-driven compatibility harnesses with fake modules for CircuitPython-specific imports when the unix-port path is not yet practical
- minimal subprocess-based smoke checks for package import contracts

Windows host note:

- per [Decision 0005](../decisions/0005-windows-wsl2-unix-port-validation.md), Windows contributors should use WSL2 for unix-port-based MicroPython and CircuitPython validation rather than native-Windows unix-port workflows in this phase

### Layer 3: real-device tests

Purpose:

- validate behavior that mocks cannot prove
- validate actual MicroPython and CircuitPython interpreter behavior
- validate board-facing integration points

## Proposed first device strategy

- keep `devices.yml` out of version control
- provide `devices.example.yml`
- use manually triggered workflows first
- allow a local home testbed to be attached later without changing library code
- keep the on-device test harness tiny and purpose-built

Current decision:

- hardware workflows are manual only for the initial phase
- MicroPython path should be: CPython tests, then MicroPython Unix port where practical, then later real board runs
- CircuitPython should follow the same ladder if the unix port is practical enough for this repo; otherwise start with mocks and then real board runs
- on Windows, unix-port validation should target WSL2 rather than native Windows first

Current verified state:

- `devices.example.yml` is now checked in
- the repo has a manual `test-device` entrypoint in `scripts/run.py`
- the repo can prepare a pinned local MicroPython unix-port runtime under `.tools/`
- the first MicroPython-oriented compatibility command has been exercised successfully in this workspace with the prepared local runtime
- the repo now has a real local `prepare-circuitpython` / `test-circuitpython-compat` evaluation path instead of a placeholder task
- the pinned CircuitPython `10.1.4` unix-port path now builds successfully in this macOS workspace
- the shared timing smoke runner now passes in this workspace under CPython, MicroPython unix-port, and CircuitPython unix-port

## Why not use `pytest` directly on device?

`pytest` is still likely the right orchestrator from the host side, but it is not the best assumption for constrained board execution because of footprint, plugin complexity, and dependency expectations.

The likely right split is:

- `pytest` on the host
- a tiny `support/test_harness/` for `device_tests/`

## Success criteria

- simulation/emulation is preferred when realistic
- real-device runs are opt-in and do not block basic contributor workflows by default
- board registration is explicit and local configuration stays out of version control
- device-facing tests are separated from host-only tests
- device execution paths are simple enough for both humans and agents to run repeatedly

## Notes

Do not design hardware orchestration until at least one library needs it. Keep the contract small and testable.

This workstream remains active because the transport layer, automated compatibility runs, and real-board execution path are still intentionally incomplete.

## Resolved feedback

- **CircuitPython unix-port host-runtime path:** Already pursued and verified. The pinned CircuitPython 10.1.4 unix-port builds locally on macOS and passes the timing smoke tests. It runs as an advisory CI job.

## Open decisions

- What would make you want to promote hardware workflows from manual-only to scheduled or protected-branch checks? (Likely: once board transport tooling exists and has proven reliable.)
- Which real boards do you expect to be the first-class test targets in your home testbed?

