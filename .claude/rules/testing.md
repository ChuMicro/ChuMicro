---
paths:
  - "**/tests/**/*.py"
  - "**/functional_tests/**/*.py"
  - "**/testing.py"
---

# Tests

- Pass `--coverage-threshold 94` to `test` and `preflight`.
- A cross-runtime file is the default for `tests/test_*.py`: never `import pytest`, use plain `assert` and constructor-injected fakes from the library's `testing.py`. The top docstring names the lane.
- Opt down with in-file markers. `__chumicro_runtimes__ = ("cpython",)` lifts the `import pytest` ban for fixture suites. `__chumicro_host_only__ = True` runs on CPython and the MicroPython/CircuitPython unix ports but never on silicon, for files driving runtime-specific source through host fakes. The marker is the contract; a `_pytest.py` or `test_{cp,mp}_*` filename is a hint for humans.
- Every cross-runtime file runs green on a freshly-reset Pi Pico W (264 KB) under both device runtimes. A PSRAM-only pass validates nothing. A file that OOMs there even with `--per-file` is a tracked defect.
- Import from a closed set: the package's own `src/` and `testing.py`, stdlib, pytest and its plugins, `chumicro_test_harness` and its submodules ([Decision 0082](../../plans/decisions/0082-test-harness-as-infrastructure-library.md)), and the dependencies declared in `pyproject.toml` including their `testing.py` fakes. Declare a test-only dependency in the `[test]` extra. Never import an undeclared chumicro package, never read a sibling repo's filesystem.
- Skips are loud. Use `chumicro_test_harness.skip(reason)`, a marker, or `raise AssertionError(...)`. A test with no assertion is a defect.
- A fake models the target's awkward behavior, not the easy path. A fake returning the convenient result regardless of input hides production bugs.
- A literal or `(A, B)` tolerance in production code that exists to accommodate a fake's hardcoded value means the fake is wrong, not the platform. Fix the fake to read the platform's real value. Full recognizer and a worked example: [`plans/patterns.md`](../../plans/patterns.md).
- Changes to host-side concurrency, streaming transport, marker dispatch, multi-call sequences against one transport, or abort and cleanup paths need a real-board bake before done, even with the unit suite green.
