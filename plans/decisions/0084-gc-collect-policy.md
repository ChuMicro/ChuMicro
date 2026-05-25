# Decision 0084: `gc.collect()` policy — three named contexts, no others

Status: `accepted`
Date: `2026-05-24`
Summary: `gc.collect()` forbidden in hot paths; required at end of library `__init__.py` with substantial top-level state; recommended after a large-blob method; allowed between state changes.
Related: Decision 0015 (256 KB MCU RAM tier — the constraint this rule exists for), Decision 0042 (library dependency policy — multi-file libraries collect between submodule imports), Decision 0065 (device-library scaffolding cost — sibling rule about library shape on small boards).

## Context

The 256 KB-RAM board tier (Decision 0015) leaves no slack for accidental heap fragmentation. MicroPython's compiler leaves AST scratch + transient tuples interleaved with a library's persistent state at module import time, and auto-GC may not fire to reclaim it — measured +33 KB contiguous heap on Pi Pico W MP for the `chumicro_mqtt` + `chumicro_sockets` import chain, enough to flip TLS handshakes from `ENOMEM` to `ROUND_TRIP`. Without a named policy, library authors either collect compulsively (steals time from the hot path) or never (loses the import-time reclaim).

## Decision

`gc.collect()` has three named contexts; no fourth.

- **Forbidden in hot paths.** A `gc.collect()` reachable from a runner `tick()` / `handle()` / `check()` signals missing pre-allocation. The fix is pre-allocation (module-level constants, pre-allocated `bytearray` buffers, reused scratch containers), not a collection call. Hot-path collects steal time from the work being done.

- **Required after substantial import-time state.** Any library `__init__.py` whose top-level imports build substantial state (parsers / decoders, multi-class setups, runtime-specific adapter loads, module-scope `const()` tables) imports `gc` at the top and calls `gc.collect()` at the end:

  ```python
  import gc

  # ... module body / imports / setup ...

  gc.collect()
  ```

  Heavy multi-file libraries (mqtt, websockets) also call `gc.collect()` between submodule imports inside `__init__.py`. Tiny single-purpose libraries (a polyfill, a logger config, one small dataclass) don't earn the boilerplate. The earlier `import gc as _gc; _gc.collect(); del _gc` pattern is not used: `gc` is sys.modules-resident either way, the alias-delete doesn't reclaim memory, and `gc` appearing as a sub-attribute of the package is harmless since any consumer can `import gc` directly.

- **Recommended after handling a large blob; allowed between other state changes.** When a method handles a large bytearray, parsed payload, or decoded image, `del` the locals and call `gc.collect()` before returning — natural method-exit cleanup is too slow for large allocations, and immediate collection reduces fragmentation and RAM pressure. Other "between state changes" points (post-handshake, post-`connect()`) are allowed at the author's discretion, marked with a comment naming the reason.

Benign on CPython: its GC model has no MicroPython compiler-scratch problem, so the import-time collect is a no-op there.

## Rejected alternatives

- **Always collect after every operation.** Cost outweighs benefit on hot operations and trains agents not to reason about allocation hygiene at the source.
- **Never collect; rely on auto-GC.** Loses the import-time reclaim on MicroPython; the +33 KB difference is load-bearing on Pi Pico W.
- **Auto-collect via decorator / context manager.** Hides the discipline behind a convenience and makes allocation hygiene invisible to review.

## Consequences

- The rule itself lives in AGENTS.md as a non-negotiable; this ADR carries the rationale + measured evidence that justifies it under push-back.
- New libraries with substantial import-time state add the `gc.collect()` boilerplate at scaffold time.
- Hot-path `gc.collect()` calls flagged in code review or `/audit-embedded` passes are a defect signal, not "defensive programming."
- A CHU lint detecting hot-path `gc.collect()` reachable from `tick()` / `handle()` / `check()` paths via call-graph analysis is plausible future work, not in scope here.
