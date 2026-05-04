# Decision 0050: Library inclusion test — what counts as a chumicro library

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0010 (testability + fakes), Decision 0014 (runner pattern), Decision 0015 (board support tiers), Decision 0042 (library dependency policy), Decision 0049 (three runtimes), Decision 0032 (workbench host tools — different inclusion test).

## Context

The chumicro library catalogue (`timing`, `runner`, `compat`, `logging`, `events`, `msgpack`, `config`, `kvstore`, `wifi`, `sockets`, `ntp`, `requests`, `http_server`, `mqtt`, `websockets`) grew organically as the workspace's needs surfaced.  AGENTS.md presents the list as a fait-accompli table.  But several ADRs (0042 dep policy, 0046 lazy folders, 0049 trinity) implicitly fix what *qualifies* as a library, without naming the rubric.

A future contributor proposing `chumicro-bluetooth`, `chumicro-i2c-eeprom`, or `chumicro-cellular` needs a clear test for "should this be a chumicro library, a workbench package, or out of scope?"  Without it, the catalogue accretes by argument-of-the-day.

## Decision

A package qualifies for `libraries/<name>/` if it meets **all** of the following:

1. **Three-runtime native.** Runs on CPython, MicroPython, and CircuitPython under the same import path.  Per-runtime backends live inside the library as `_adapters/` or `_backends/` subpackages, marked with `__chumicro_runtimes__` (Decision 0037).  Pure-Python; no CPython-only third-party deps.
2. **Runner-shaped, or callable from a runner.** If the library owns time or I/O, it exposes the runner contract (`check(now_ms) -> bool` + `handle(now_ms)`) per Decision 0051.  Pure-functional libraries (msgpack, compat) opt out of the contract — they're called synchronously from runner-shaped consumers.
3. **Ships a `testing.py`** with fakes if it owns time, I/O, or non-deterministic behavior (Decision 0010).  The fake declares `__chumicro_runtimes__ = ("cpython",)` so it ships only in PyPI sdists / wheels.
4. **Fits Decision 0015's hardware floor** — 256 KB MCU RAM, 4 MB flash.  Libraries that need more get a `requires_flash = true` marker (Decision 0047) but don't escape the floor.
5. **Slots cleanly into Decision 0042's dependency classes** — either core infrastructure (Class 1, hard dep + factory helper) or decoration (Class 2, callbacks only).  Libraries that want to be "sometimes imported, sometimes not" don't qualify; they're either always-on or never-imported.

A package qualifies for `workbench/<name>/` if it's host-only (Decision 0032).  Different inclusion test, different rules — workbench packages can carry CPython-only deps, never load on devices, and don't ship to the bundle.

A package belongs out of scope (third-party / vendored) if it's pure-Python and runtime-portable but doesn't earn its keep — chumicro doesn't fork upstream libraries to "make them ours."  We use them as deps when they meet Decision 0007's cross-platform test, or vendor them as `packages/` payload when they don't ship to one of our runtimes.

## Rejected

**Inclusion by hardware adjacency.**  "It plugs into a board" isn't enough — any pure-Python library *can* plug into a board.  A library qualifies only when chumicro-specific patterns (cross-runtime adapters, runner shape, testing fakes, hardware floor) earn the chumicro home.

**Inclusion by user demand.**  "Several users want this" is necessary but not sufficient.  A library that fails the runner-shape test (e.g., a synchronous-blocking SD card driver) doesn't graduate just because users want it — it needs to be re-shaped first, or shipped under a different name (`workbench/`, third-party PyPI, or vendored payload).

## Consequences

- New library proposals start with the rubric.  Failing any of the five rules sends the proposal to a different home (workbench, third-party, vendored).  An ADR or workstream entry records the call for future reference.
- The current 15-library catalogue all pass the rubric.  Where they don't quite fit (e.g., `chumicro-config` doesn't expose a runner contract — it's pure-functional), the package is functional rather than a service, which the rule explicitly allows.
- Hardware-specific drivers (e.g., a future LCD driver) live as adapters inside a more general library if a general slot exists, or as their own library if cross-runtime adapter-shaping is non-trivial.
- A future `chumicro-bluetooth` would qualify if pure-Python and adapter-able across CP+MP+CPython substrates; it would not qualify if it required wrapping vendor C SDKs that have no CPython equivalent.
- Workbench-vs-libraries close calls (e.g., a host-side tool that drives a device but also has a tiny on-device payload) follow Decision 0032 §1 — the *installer's destination* decides the folder, not the file mix.
