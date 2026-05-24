# Decision 0010: Library and workbench testability

Status: `accepted`
Date: `2026-04-01`
Summary: Libraries use constructor injection for time/I/O/network; each ships its own `testing.py` fakes in `src/`; shared fakes are duplicated, never hoisted.
Related: Decision 0014 (runner pattern uses injected ticks), Decision 0042 (library dependency policy), Decision 0044 (deploy-time runtime filtering keeps fakes out of bundles), Decision 0052 (workbench-no-library-imports — the same self-contained instinct in the opposite direction)

## Context

Libraries and workbench packages need to be testable both by their own test suites and by downstream consumers (other packages, user code, AI agents writing tests).  Without explicit guidance, packages tend to hard-wire dependencies (e.g., calling `time.monotonic()` directly) making them impossible to test without monkeypatching or live hardware.

## Decision

Libraries and workbench packages must be designed for testability from the start:

### 1. Accept dependencies via constructor injection

Classes that depend on external services (time, I/O, network) must accept those dependencies as constructor parameters rather than importing them directly in methods.

```python
# Good — testable
class Heartbeat:
    def __init__(self, period_ms: int, ticks: object | None = None) -> None:
        self._period_ms = period_ms
        # Inject a ticks source (e.g. FakeTicks) for tests; default to the
        # real clock in production.
        self._ticks = ticks

# Bad — not testable without monkeypatching
class Heartbeat:
    def __init__(self, period_ms: int) -> None:
        self._period_ms = period_ms

    def is_due(self) -> bool:
        now = time.monotonic_ns()  # hard-wired
```

The real signature in `chumicro_timing.heartbeat.Heartbeat` follows this shape:
`__init__(self, period_ms: int, ticks: object | None = None)`.

### 2. Provide fakes for things you own

Packages that expose types or functions others will need to mock must include a `testing` submodule with ready-made fakes.

- Path: `src/chumicro_<name>/testing.py`
- Import: `from chumicro_<name>.testing import Fake<Thing>`
- Pattern follows `django.test`, `flask.testing`

Fakes ship in `src/` alongside production code so they are importable by any library's test suite via PYTHONPATH — no pip install needed.

### 3. Prefer provided fakes over ad-hoc mocks

When testing code that uses another ChuMicro package, prefer that package's provided fakes over `unittest.mock`.  Fakes stay consistent with the real implementation as the upstream evolves, and they give tests better steering (e.g., manually advancing time with `FakeTicks`).

`unittest.mock` is not banned — it's fine when a purpose-built fake doesn't exist or doesn't make sense for the situation.  But if a package ships a `testing` submodule with fakes designed for exactly your use case, reach for those first.

### 4. Never hoist shared test fakes

Test fakes stay co-located with the package they test, even when two or more packages independently re-define the same fake.  `FakeTime` exists in both `chumicro_deploy.testing` and `chumicro_repl.testing` — the second is a docstring-marked mirror of the first, not an import of it.  No `chumicro-workbench-fakes` shared package.

Reasoning:

- **Tiny and stable.**  The fakes we share in practice are small (~80 lines) and implement stable protocols (`monotonic()`, `recv_into()`, etc.) that don't churn.  Duplication scales linearly with zero maintenance burden.
- **Test fakes are internal, not API.**  Divergence between two packages' fakes has no user consequence — each fake serves the test contract of its own package.
- **A shipped test-dependency has bad shapes either way.**  A regular PyPI dep is always installed (waste — users don't run our tests).  A `[test]` extra creates version-skew across consumers (one package pins one version, another pins a different one, release coordination headache).  Neither shape beats N copies of an 80-line fake.
- **If a protocol type itself ever needs centralizing, it goes in `support/`** (internal); the fake doesn't follow it.

Decision 0052 (workbench-no-library-imports) carries the same instinct in the opposite direction — packages stay self-contained — and this rule is the workbench-test-fake corollary.

## Consequences

- Every package that provides injectable services (ticks, I/O, network) must also provide fakes in a `testing` submodule.
- The `new-library` scaffolder does not create the `testing` submodule by default — add it when the package has something worth faking.
- Downstream packages import fakes directly (`from chumicro_timing.testing import FakeTicks`) with no additional setup beyond PYTHONPATH.
- Test fakes are covered by the package's own test suite (they are production code in `src/`).
- This pattern makes packages extractable: the `testing` submodule travels with the package when it leaves the mono-workspace.
