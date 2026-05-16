# Cross-runtime harness: class-based test discovery

## Why

The cross-runtime test harness discovers only **module-level**
`def test_*` functions: `_parse_test_functions`
(`workbench/pytest-device/src/chumicro_pytest_device/plugin.py` ~L586)
keeps `ast.FunctionDef` nodes whose name starts with `test_`, and
ignores `ast.ClassDef`.  So `class TestX: def test_y(self)` suites are
invisible to the `--target unix-port` and `--target device-unit`
lanes — they ran only on plain CPython `pytest`.

This was silent until the on-device sweep (Decision 0068) exposed it.
A loud collection guard now fails any device-lane
`libraries/<n>/tests/test_*.py` that yields zero discoverable tests,
so the gap can no longer hide.  As an interim measure, 16 class-based
files carry `__chumicro_runtimes__ = ("cpython",)` to keep them in the
CPython lane explicitly (greppable, guard-satisfying).

**The intended end state is harness support for class-based tests, not
converting ~800 tests to module-level functions.**  When the harness
discovers class methods, the 16 interim markers are removed and those
suites run cross-runtime + on-device as their location implies.

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

## Acceptance

- `_parse_test_functions` (or its replacement) discovers `class Test*`
  methods; a class-based file yields the right item count under
  `--target unix-port` and `--target device-unit`.
- The 16 markers + stopgap comments are gone; `grep` finds no
  `__chumicro_runtimes__ = ("cpython",)` whose only reason was
  class-shape.
- The loud guard still fires for a genuinely empty/mis-shaped file
  (regression test).
- 4-board matrix sweep green or with only triaged, understood
  per-test failures.

## Related

Decision 0016 (cross-runtime unit tests — amended in place to record
the interim marker rule + the loud guard), Decision 0058 (loud
skips), Decision 0068 (the on-device sweep that exposed this),
Decision 0070 (the host-only/lane marker mechanism the interim
marker reuses).
