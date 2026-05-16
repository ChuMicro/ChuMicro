# Decision 0069: Explicit test-support module marker

Status: `accepted`
Date: `2026-05-15`
Related: [Decision 0037](0037-runtime-file-marking.md) (per-runtime file marking — this splits one concern out of it), [Decision 0044](0044-deploy-time-runtime-filtering.md) (deploy-time filtering — gains a test-support rule + a unit-sweep exception), [Decision 0010](0010-library-testability.md) (`testing.py` fakes), [Decision 0016](0016-cross-runtime-unit-tests.md) (cross-runtime unit suite), [Decision 0068](0068-unified-deploy-mode-resolution.md) (the on-device unit sweep that surfaced this).

## Context

Decision 0037 §3 gave `testing.py` the marker `__chumicro_runtimes__ = ("cpython",)` purely to make the deploy/bundle filter drop it from bundles and devices.  That marker is **false**: the fakes run on MicroPython and CircuitPython every preflight, via the cross-runtime unit suite on unix-port (Decision 0016) which imports `chumicro_<lib>.testing` fakes and executes them on the MP/CP interpreter.  The marker conflated two orthogonal properties — *which runtimes a file can execute on* (none restricted, for `testing.py`) and *whether a file is test-support that must never ship in a product/bundle* (yes).

Decision 0068's on-device unit sweep (`--target device-unit`) made the conflation a defect: 21 of 37 cross-runtime unit-test files import a `*.testing` fake, the device transport applies the Decision 0044 marker filter, so every fake-using suite `ImportError`s on the board — while the identical tests pass on unix-port (which stages nothing — it runs in place, no filter).

## Decision

A dedicated module-level marker declares test-support, independent of runtime:

```python
# chumicro_<lib>/testing.py
__chumicro_test_support__ = True
```

`testing.py` files **drop** `__chumicro_runtimes__` (they are not runtime-restricted) and declare `__chumicro_test_support__ = True` instead.  A test-support module is one that exists only to support tests (fakes, harness shims) and must never reach a shipped product.

A reader `is_test_support_module(path) -> bool` lives beside `read_runtime_marker` in `chumicro_deploy.runtime_marker` (AST-only — no execution; re-exported from `chumicro_deploy`).

Filtering rule, applied at every host-side copy boundary that Decision 0044 governs:

- **Bundle pipeline + product/app/functional device deploys**: exclude test-support modules — exactly the boundaries `("cpython",)` excluded `testing.py` from before.  Behaviour for shipped artifacts is unchanged.
- **The on-device unit sweep** (`--target device-unit`, Decision 0068): test-support modules are **included**.  The transport `stage()` takes an `include_test_support` flag, default `False`; only the device-unit staging path passes `True`.  This is the one explicit exception, scoped to a test context, never to a deploy that reaches a product.
- **unix-port**: unchanged — it stages nothing, so no filter applies; the fakes resolve on `sys.path` as before.
- **PyPI sdist / wheel**: unchanged — `python -m build` ships every file under `src/`; not routed through the filter.

### Alternatives considered

- **Keep the `("cpython",)` runtime marker, add only a device-unit bypass.**  Smallest diff, but leaves the marker a documented lie (`testing.py` runs on MP/CP) and keeps "no fakes in products" implicit in marker-abuse rather than a named, testable rule.
- **Re-mark `testing.py` all-runtime, exclude by filename.**  Filename-matching (`basename == "testing.py"`) is the kind of path-inference Decision 0037 §2 explicitly rejected for runtime files — a renamed/moved helper silently regresses.  A marker is the contract.
- **Re-mark all-runtime with no exclusion.**  Ships fakes into every product/bundle — regresses the flash-footprint win that motivated Decision 0037.

## Consequences

- `__chumicro_runtimes__` is honest again: it means "runtimes this file can execute on," nothing else.  `testing.py` carries no runtime restriction (correct — it runs wherever tests run).
- "Test-support never ships to a product" is a first-class, greppable, AST-readable rule with a regression test asserting `testing.py` is present in a `device-unit` stage and absent from every bundle and product/functional deploy.  A missed exclusion site is caught by that test, not by a consumer.
- Decision 0037 §3 and its marker table, and Decision 0044's filtering layers, are edited in place to describe the test-support marker and the unit-sweep inclusion exception.
- The on-device unit sweep can finally run fake-using suites on hardware, unblocking Decision 0068 Phase 4 validation.
- Adding a new test-support module means declaring `__chumicro_test_support__ = True` — there is no path-based guess, mirroring Decision 0037 §2's marker-is-the-contract principle.
