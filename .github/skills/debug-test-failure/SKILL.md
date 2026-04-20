---
name: debug-test-failure
description: How to diagnose and fix test failures from run.py test or preflight. Use this skill when tests fail and you need to isolate the problem.
---

# Debug Test Failure

When `python scripts/run.py test` or `preflight` reports test failures, follow this procedure to isolate and fix the problem.

## 1. Identify what failed

If the failure came from `preflight`, the output tells you which step failed:

```
Preflight failed at: test (python 3.14)
```

For test failures, look for the pytest summary. Find the failing test names:

```bash
python scripts/run.py test --all 2>&1 | grep -E "FAILED|ERROR"
```

## 2. Re-run the failing library in isolation

Don't re-run all tests. Target the specific library:

```bash
python scripts/run.py test --libraries timing -v --no-cov -x
```

Flags:
- `--libraries timing` — only this library
- `-v` — show individual test names and results
- `--no-cov` — skip coverage (faster, less noise)
- `-x` — stop on first failure

## 3. Re-run a single test

Use `-k` with the library-scoped filter:

```bash
# By test name (matches any test containing "ticks_diff" in the timing library)
python scripts/run.py test -k timing/ticks_diff --no-cov -v

# By file and test name
python scripts/run.py test -k timing/test_ticks/ticks_diff --no-cov -v
```

## 4. Read the failure output

Pytest shows:
- **The assertion that failed** — what was expected vs. what happened.
- **The traceback** — which line in the test and which line in the source.
- **Local variables** — pytest's `-v` output shows variable values at the failure point.

If the output is truncated, redirect to a file:

```bash
python scripts/run.py test -k timing/ticks_diff --no-cov -v > .scratch/test-output.log 2>&1
```

Then read `.scratch/test-output.log`.

## 5. Common failure patterns

### Coverage below 94%

```
FAIL Required test coverage of 94% not reached. Total coverage: 91.20%
```

**Fix:** Check the coverage report for uncovered lines (`Missing` column). Write tests that exercise those branches. To see the report without the gate blocking:

```bash
python scripts/run.py test --libraries timing 2>&1 | grep -A 100 "^Name"
```

Lines marked in the `Missing` column need test coverage. Branch coverage misses show as `X->Y` in `BrPart`.

### Import errors

```
ModuleNotFoundError: No module named 'chumicro_timing'
```

**Fix:** Run `python scripts/run.py sync-ide` to regenerate PYTHONPATH configs. The test runner adds `src/` directories automatically, but IDE runs may not.

### Test isolation failures

A test passes alone but fails when run with others.

**Fix:** Check for shared mutable state. Tests should not modify module-level variables. Use the `fake_workspace` pattern or `monkeypatch` fixtures for isolation.

### Cross-runtime compatibility failures

```
Preflight failed at: test-micropython-compatibility
```

**Fix:** The cross-runtime tests run under MicroPython/CircuitPython unix-port. Common causes:

- Using CPython-only stdlib modules (e.g., `functools`, `typing`)
- f-string expressions too complex for MicroPython
- Using `match`/`case` or walrus operator (not supported on all runtimes)

Check the compat test output:

```bash
python scripts/run.py test-micropython-compatibility 2>&1 | tail -20
```

### Griffe warnings in docs build

```
Preflight failed at: docs
Docs build has griffe warnings: libraries/timing
```

**Fix:** A docstring is missing or has malformed type annotations. The docs build enforces zero griffe warnings (Decision 0021). Check the warning text — it names the symbol and issue. Fix the docstring in the source.

### verify-examples failure

```
FAIL: libraries/timing/examples/quickstart.py  (cannot import module 'chumicro_timing')
```

**Fix:** The example imports a symbol that doesn't exist or was renamed. Check `__init__.py` exports match what the example imports.

## 6. Fix and verify

After fixing, re-run the specific failing test first:

```bash
python scripts/run.py test -k timing/ticks_diff --no-cov -v
```

Then run the full library:

```bash
python scripts/run.py test --libraries timing
```

Then preflight if the original failure came from there:

```bash
python scripts/run.py preflight 2>&1 | tail -5
```
