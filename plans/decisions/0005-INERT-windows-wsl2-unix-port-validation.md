# Decision 0005: Windows host path for unix-port validation

Status: `accepted`
Date: `2026-03-29`
Related: Decision 0003 (test boundaries), Decision 0016 (cross-runtime unit tests)
Archived: inert — an explicitly provisional early-phase Windows-host intent that was never operationalized: no live setup doc adopted the "native CPython + WSL2" path it predicted, and the current posture moved past it (the deploy tool hard-refuses native Windows; the docs state Windows is not currently supported). No successor ADR. Historical record only; see [Decision 0076](0076-archive-dead-decisions-in-filename.md).

## Context

ChuMicro wants a developer environment that works across macOS, Linux, and Windows, but the early target-runtime validation path depends on Unix-like execution targets such as the MicroPython Unix port and CircuitPython `ports/unix/` workflows.

The repo already has compatibility-oriented task entrypoints in `scripts/run.py`, but it does not yet have a proven native-Windows strategy for those Unix-port checks.

## Decision

Treat Windows as a supported development host for CPython work, but use **WSL2** as the supported Windows path for Unix-port-based MicroPython and CircuitPython validation.

For the current phase:

- native Windows remains acceptable for editing, linting, host-side tests, packaging, and IDE work
- WSL2 is the recommended Windows environment for unix-port compatibility checks
- native Windows unix-port builds are out of scope for the current workspace phase
- this decision does not claim that CircuitPython unix-port validation is already proven in this repo; it only defines the intended Windows host path once that validation is implemented

## Consequences

- future setup docs can describe Windows support as `native CPython + WSL2 for unix-port validation`
- MicroPython compatibility work can assume a Unix-like shell on Windows instead of supporting native-Windows unix-port workflows immediately
- CircuitPython unix-port evaluation on Windows should target WSL2 rather than native Windows first
- the repo can stay cross-platform for general development without overcommitting to native-Windows parity for Unix-port runtime checks too early
