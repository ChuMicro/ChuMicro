# Cross-runtime harness: class-based test discovery

## Why

The host-side AST collector `_parse_test_functions`
(`workbench/pytest-device/src/chumicro_pytest_device/plugin.py`) kept
only `ast.FunctionDef` nodes, ignoring `ast.ClassDef`.  So
`class TestX: def test_y(self)` suites were invisible to the `--target
unix-port` and `--target device-unit` lanes — they ran only on plain
CPython `pytest`.  The on-device runner (`runner._iter_test_functions`)
*did* discover class methods; the gap was host-side collection only.

The on-device sweep (Decision 0068) exposed it; a loud collection
guard was added so a zero-discovery device-lane file can no longer
hide, and ~16 class-based files carried an interim
`__chumicro_runtimes__ = ("cpython",)` marker as a stopgap.

**The chosen fix is harness support for class-based tests, not
converting ~800 tests to module-level functions.**  This has landed
for the bench-free path: the collector now emits `ClassName.test_method`
qualified names (the format the runner already produces), the interim
markers are reverted, and the suites pass cross-runtime on MP + CP
unix-port.  The on-device (`--target device-unit`) 4-board confirmation
is the one remaining hardware-gated step — see Status.

## Scope

1. Extend the harness's AST discovery to find test methods inside
   `class Test*` (and the on-device runner in
   `support/test_harness/src/chumicro_test_harness/runner.py`, which
   already iterates `dir()`/attrs — confirm class-method execution
   parity).  No pytest dependency on-device (Decision 0016): plain
   `class TestX:` with `def test_y(self)` + plain asserts, instantiated
   and called by the harness, not pytest.
2. Decide fixture story: these suites use pytest class patterns but
   (per the audit) **no** `@pytest`/fixtures/`monkeypatch` — verify and
   keep it that way, or the file stays CPython-lane.
3. Remove the interim `__chumicro_runtimes__ = ("cpython",)` marker +
   the stopgap comment from the 16 files once discovery + on-device
   execution pass:
   - `http_server/tests/test_http_server.py`
   - `mqtt/tests/test_{client,decoder,encoder,packets,state,testing_helpers}.py`
   - `requests/tests/test_requests.py`
   - `sockets/tests/test_{factories,protocol,testing}.py`
   - `websockets/tests/test_{client,integration,server,sockets_factory,websockets}.py`
   - `sockets/tests/test_cp_adapter.py` — **special**: class-based
     *and* host-context.  Carried `__chumicro_host_only__` (Decision
     0070) but, being class-based, also silently yielded zero on the
     unix-port lane where host-only is supposed to run; the zero-item
     guard caught it.  Interim-marked `__chumicro_runtimes__ =
     ("cpython",)`; when harness class-discovery lands this reverts to
     `__chumicro_host_only__ = True` (its true lane), **not** plain
     device-lane.
4. Re-run the 4-board sweep — these ~800 methods now execute on
   MP/CP unix-port and on-device; triage any genuine cross-runtime
   failures (the sweep's legitimate output).

## Status

- [x] **Scope 1 — discovery.**  The on-device runner
  (`runner._iter_test_functions`) *already* discovered class methods
  (fresh instance per test, `ClassName.test_method` qualified names) —
  the gap was host-side only.  `_parse_test_functions` (plugin.py)
  extended to walk top-level `class Test*` and emit the **identical**
  `f"{class_name}.{attr}"` format, so collection items / single-test
  name filters / per-item reporting line up with execution.  No
  on-device runner change needed.
- [x] **Scope 2 — fixture story.**  The pytest "hits" in the
  revert-scope files were all comments pointing at sibling
  `*_pytest.py` files; none import pytest or use fixtures.  The
  genuine pytest-fixture suites stay `("cpython",)` (all 14 remaining
  markers are `*_pytest.py`).
- [x] **Scope 3 — markers reverted.**  16 files lost the
  `("cpython",)` marker + stopgap comment; `sockets/tests/test_cp_adapter.py`
  reverted to `__chumicro_host_only__ = True` (its true lane).
- [x] **Scope 4 (unix-port) — bench-free cross-runtime triage.**
  Full reverted set on MicroPython **and** CircuitPython unix-port:
  882 passed / 4 legit skips / 0 fail per runtime.  One genuine
  defect surfaced and fixed (the sweep's legitimate output):
  `chumicro_sockets._adapters.cp.ssl_context_with_ca` did `import ssl`
  *before* its documented "up front" PEM/DER validation, so the clear
  ValueError was unreachable where the ssl/tls binding is absent (CP
  unix-port / minimal builds).  Validation moved above the import —
  pure string inspection, no behavior change on real boards, makes the
  docstring's "up front" promise true.
- [x] **Scope 4 (on-device) — 4-board confirmation.**  `--target
  device-unit` `websockets` (5 reverted class files, 288 class-qualified
  methods) across the canonical matrix in flash mode:
  - Lolin S2 **CP** (PSRAM): **288 / 0 / 0**
  - Lolin S2 **MP** (PSRAM): **288 / 0 / 0**
  - Pi Pico W **CP** (264 KB): 15 / 274 — `MemoryError` in
    `discovery._exec_as_namespace`
  - Pi Pico W **MP** (264 KB): 91 / 197 — `MemoryError: allocating
    14848 bytes`

  Class discovery on real silicon is **validated**: the device executes
  class-qualified `ClassName.test_method` names, and both PSRAM boards
  run every reverted class method green on both runtimes.  The Pico W
  failures are **not** a discovery defect or a regression (these methods
  never ran on-device before): they are a 264 KB whole-module-`exec()`
  RAM ceiling — `_exec_as_namespace` execs each test file as one
  namespace, and a large class module (`test_websockets.py`, 136 tests)
  exceeds the budget; small files pass on the Pico W too
  (`test_integration` 10/10, `test_sockets_factory` 5/5).  This is the
  sweep's legitimate output per the deploy-mode-unification 4d framing
  (per-library on-silicon conformance is output, not a gate).  Recorded
  as a harness follow-up below; the bench-free landing is unaffected.

### On-device follow-up — two memory walls, one closed

Investigating the Pico W OOM (bench, boards live) found **two distinct
memory walls** for a large class-organized module on a 264 KB board in
flash mode.  PSRAM boards (Lolin S2) hit neither — websockets 288/0/0
on CP+MP.

1. **Compile transient — CLOSED.**  `discovery._exec_as_namespace` fed
   the whole 1212-LOC source to one `exec()`; MicroPython /
   CircuitPython compile the entire argument at once, and that peak
   exceeded the Pico W.  Fixed: the host (`_test_runner.chunk_boundaries_for`,
   CPython `ast`, decorator-aware) computes top-level statement start
   lines and the device exec's the file in per-statement chunks into
   one shared namespace (`discovery._exec_chunked`), bounding the
   compile peak to the largest single statement.  Newline-left-padded
   so tracebacks keep real line numbers; `None` boundaries keep the
   single whole-file exec (CPython / unix-port unaffected); a
   `from __future__` import or <2 statements disables it.  MP-safe
   (no PEP 448 set unpacking — this runs on-device).  Verified: the
   device now compiles the big module and proceeds into execution.

2. **Resident co-residency — RESOLVED by [Decision 0072](../decisions/0072-large-test-modules-on-constrained-boards.md).**  Past
   compile, the OOM moves to importing the library while one large
   test module's defs are resident.  A single big file on a *freshly
   reset* board still OOMs, so this is **not** cumulative `sys.modules`
   (Decision 0071) — genuine co-residency of one large test module +
   the library + the harness exceeding 256 KB.  Chunked *compile*
   cannot fix a *resident* ceiling.  Resolution (Decision 0072):
   - **Opt-in `--per-file` reset — implemented.**  `scripts/run.py
     test-unit-on-device --per-file` / `pytest ... --per-file`
     soft-resets the interpreter before each test *file* (Decision
     0071's per-library reset extended to per-file granularity, no
     re-stage — the tree persists on the device FS), idempotent across
     the two `prepare()` calls per batch.  Default stays per-library
     (fast).  Plugin + `scripts/run.py` + 7 unit tests; preflight green.
   - **Reactive split — documented, non-mechanized.**  No tests-per-file
     cap or CHU lint; the ceiling is library-weight-dependent (coarse
     Pico W CP measurement: heavy `_wire` libs ≈32–61 tests/file
     fresh).  Caution + split-when-it-OOMs in `device-testing.md`;
     `/audit-library` + `/audit-embedded` carry the cross-ref pointer.
   Hardware: the mechanism is wired and unit-proven; on mqtt/websockets
   the dominant wall is single files individually over the ceiling
   (`test_client` 80, `test_websockets` 136) — the documented
   reactive-split set, not an accumulation `--per-file` flips.  Its
   payoff is realized paired with those splits (next).

Neither wall affects the bench-free landing or the PSRAM-board
validation.

## Acceptance

- [x] `_parse_test_functions` discovers `class Test*` methods; a
  class-based file yields the right item count under `--target
  unix-port` (verified: `mqtt/test_client.py` collects
  `TestBoundedRecvPerTick.test_*` etc.).  `--target device-unit`
  verified on silicon: device executes class-qualified
  `ClassName.test_method` names, 288/288 green on both PSRAM boards.
- [x] No `__chumicro_runtimes__ = ("cpython",)` whose only reason was
  class-shape; the 14 remaining are all genuine `*_pytest.py`.
- [x] The loud guard still fires for a genuinely pytest-style file —
  `test_pytest_style_file_yields_nothing` documents the empty-list
  trigger; `test_finds_class_methods_qualified` /
  `test_skips_non_test_classes_and_helper_classes` cover discovery.
- [x] 4-board on-device matrix sweep with only triaged failures: both
  PSRAM boards 288/0/0; both 264 KB Pico W boards' failures triaged to
  the whole-module-`exec()` RAM ceiling (harness follow-up, not a
  discovery defect — see Status Scope 4 on-device).

## Related

Decision 0016 (cross-runtime unit tests — amended in place to record
the interim marker rule + the loud guard), Decision 0058 (loud
skips), Decision 0068 (the on-device sweep that exposed this),
Decision 0070 (the host-only/lane marker mechanism the interim
marker reuses).
