# Decision 0010: Library testability

Status: `accepted`
Date: `2026-04-01`

## Context

Libraries need to be testable both by their own test suites and by downstream consumers (other libraries, user code, AI agents writing tests).  Without explicit guidance, libraries tend to hard-wire dependencies (e.g., calling `time.monotonic()` directly) making them impossible to test without monkeypatching or live hardware.

## Decision

Libraries must be designed for testability from the start:

### 1. Accept dependencies via constructor injection

Classes that depend on external services (time, I/O, network) must accept those dependencies as constructor parameters rather than importing them directly in methods.

```python
# Good — testable
class Heartbeat:
    def __init__(self, interval_ms, ticks_ms, ticks_diff):
        self._interval_ms = interval_ms
        self._ticks_ms = ticks_ms
        self._ticks_diff = ticks_diff

# Bad — not testable without monkeypatching
class Heartbeat:
    def __init__(self, interval_ms):
        self._interval_ms = interval_ms

    def is_due(self):
        now = time.monotonic_ns()  # hard-wired
```

### 2. Provide fakes for things you own

Libraries that expose types or functions others will need to mock must include a `testing` submodule with ready-made fakes.

- Path: `src/chumicro_<name>/testing.py`
- Import: `from chumicro_<name>.testing import Fake<Thing>`
- Pattern follows `django.test`, `flask.testing`

Fakes ship in `src/` alongside production code so they are importable by any library's test suite via PYTHONPATH — no pip install needed.

### 3. Don't mock what you don't own

When testing code that uses another library, use that library's provided fakes rather than creating ad-hoc mocks.  This ensures the fake's behavior stays consistent with the real implementation as the upstream library evolves.

## Consequences

- Every library that provides injectable services (ticks, I/O, network) must also provide fakes in a `testing` submodule.
- The `new-library` scaffolder does not create the `testing` submodule by default — add it when the library has something worth faking.
- Downstream libraries import fakes directly (`from chumicro_timing.testing import FakeTicks`) with no additional setup beyond PYTHONPATH.
- Test fakes are covered by the library's own test suite (they are production code in `src/`).
- This pattern makes libraries extractable: the `testing` submodule travels with the library when it leaves the mono-workspace.

