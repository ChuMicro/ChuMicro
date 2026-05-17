# Decision 0072: Chunked test-module exec + opt-in per-file reset for the on-device sweep

Status: `accepted`
Date: `2026-05-17`
Related: [Decision 0071](0071-per-library-soft-reset-flash-sweep.md) (per-library reset — this extends it to opt-in per-file granularity; its "Not closed" per-file thread resolves here), [Decision 0068](0068-unified-deploy-mode-resolution.md) (the on-device unit sweep), [Decision 0027](0027-device-testing-infrastructure.md) (persistent raw-REPL execution model), [Decision 0028](0028-deploy-modes.md) (transport `soft_reset()`), [Decision 0016](0016-cross-runtime-unit-tests.md) (cross-runtime discovery — the forcing function), [Decision 0015](0015-board-architecture-support.md) (256 KB minimum board).

## Context

Cross-runtime class discovery now runs large class-organized test modules on-device that previously ran CPython-only. On a 256 KB board (Pi Pico W CP/MP) in flash device-unit this exposed **two distinct memory walls**; PSRAM boards (Lolin S2) hit neither (websockets 288/0/0 on CP+MP). Decision 0071 closed cross-library `sys.modules` accumulation but explicitly left per-file reset open and tracked it to `plans/open-questions.md`. This decision resolves both walls.

## Decision

### 1. Chunked module exec (wall 1 — compile transient) — implemented

MicroPython / CircuitPython compile a whole `exec()` argument at once; a ~1200-LOC class module's compile peak alone exceeds 256 KB. The host (CPython, has `ast`) computes decorator-aware top-level statement start lines (`_test_runner.chunk_boundaries_for`); the device execs the file in per-statement chunks into one shared namespace (`discovery._exec_chunked`), bounding the compile peak to the largest single statement. This is semantically identical to one `exec` (shared globals, source order). Chunks are newline-left-padded so tracebacks keep real source line numbers. `chunk_boundaries=None` keeps the single whole-file exec (CPython / unix-port unchanged); a `from __future__` import or fewer than two top-level statements disables chunking (each chunk compiles independently). Implemented with plain list ops — no PEP 448 set unpacking; this module runs on-device.

### 2. Opt-in `--per-file` reset (wall 2 — resident co-residency) — decided; implementation tracked in the workstream

Past compile, one large test module's resident defs + the library + the harness can still exceed 256 KB on a freshly reset board running that file alone — distinct from Decision 0071's cumulative `sys.modules` (a single file on a fresh board still OOMs; verified on hardware). The on-device sweep gains an opt-in `--per-file` mode that soft-resets before each test *file* (Decision 0071's per-library reset extended to per-file granularity), giving each file a clean interpreter: `library + one file + harness`, no accumulation. The default stays the fast per-library-reset accumulating path — PSRAM boards and small libraries do not need per-file reset, which adds a Ctrl-D + raw-REPL re-entry per file.

Paired with a **documented, non-mechanized caution** (in the style guide / `docs/contributing/device-testing.md`): a very large class-organized module can exceed a 256 KB board's resident budget even with per-file reset; if a file OOMs on the smallest target, split it to mirror its source module. No rigid tests-per-file cap and no CHU lint — the ceiling is library-weight-dependent (coarse Pi Pico W CP measurement: heavy `_wire`-backed libraries ≈32–61 tests/file fresh), so a fixed number misfits most files. This ADR owns the policy, its doc home, and the cross-reference pointer added into `/audit-library` + `/audit-embedded` once `--per-file` lands (not before — do not document a mechanism that is not real).

### Alternatives considered

- **Sub-batch within a file (reset between batches, re-import the library per batch).** More code, slower (re-import per batch), and a file too big to compile-or-hold needs chunked exec anyway. Per-file reset is the simpler grain and the standard embedded-test-harness shape (MicroPython's own runner runs files independently for memory isolation).
- **Rigid tests-per-file cap + CHU lint.** The ceiling is library-weight-dependent, not universal; a fixed cap is wrong for most files and over-restrictive everywhere. Caution + reactive split is the cheapest rule that closes the realistic case.
- **Document a per-board ceiling only, no mechanism.** Distinct from Decision 0071's rejected "document a library ceiling": 0071 refused to punt a *reducible* cross-library accumulation; here per-file reset *is* the mechanism, and the documented caution covers only the *irreducible* residual (one file too large to be resident even alone — physics, not accumulation). Not a contradiction of 0071.
- **Split all large test files preemptively.** A workaround for a harness limit when OOM-driven; the `chumicro_requests` test-quality audit confirmed the suite is not over-tested, so blanket splitting is unwarranted. Reactive split on observed failure is the policy; genuine source-cohesion splits (e.g. requests `_wire`-vs-`client`) proceed on readability grounds independently.
- **Accept the ceiling, no per-file mode.** Leaves the cheapest supported board class unable to run the on-device sweep it exists for, while PSRAM boards pass — abandons the 256 KB tier for large suites.

## Consequences

- Wall 1 is closed (chunked exec landed). Any module that is compile-heavy but resident-OK now runs on a 256 KB board where it previously OOM'd at compile.
- Decision 0071's "Not closed by this decision" per-file-reset thread is resolved here (0071 edited in place to point here); `plans/open-questions.md` thread 1 closes on `--per-file` landing.
- Default sweep behavior is unchanged (per-library reset). `--per-file` is opt-in, materially slower, for 256 KB boards / large suites.
- The style guide / `device-testing.md` gain the reactive-split caution, and `/audit-library` + `/audit-embedded` get a one-line cross-reference pointer — both only once `--per-file` is implemented.
- The observed-OOMing files (websockets 136, requests 172 — split for source cohesion regardless, http_server 123, mqtt_client 80) are the concrete reactive-split set.
- The flash-mode per-file-reset gap is now a recorded, opt-in-resolvable design property, not an implicit limit a reader rediscovers on a 256 KB board.
