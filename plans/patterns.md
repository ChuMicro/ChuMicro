# Patterns

> **Note:** This file is primarily for AI agent context recovery — it gives agents a quick reference for implementation patterns without re-reading all the source code. Human contributors should use the [Style Guide](../docs/contributing/style-guide.md) and [Adding a New Library](../docs/contributing/new-library.md) guides instead.

Reusable implementation patterns specific to this codebase.  Follow these
when writing new libraries or modifying existing ones — they were established
because incorrect implementations caused real bugs.

For *why* these patterns exist, see the linked decisions and `history.md`.
For *rules* agents must follow, see `AGENTS.md`.  This file is the *how*.

---

## Service pattern (Runner-compatible)

Libraries that have active components (polling, scheduling, state machines)
implement the `check(now_ms) -> bool` / `handle(now_ms)` contract so they
work with `Runner.add(obj)` (Decision 0014).

```python
class MyService:
    """One-line description.

    Args:
        dependency: Injected dependency.
        interval_ms: How often to act, in milliseconds.
        ticks: Tick source (must have ``ticks_ms``,
            ``ticks_diff``, ``ticks_add``).  Defaults to real clock.
    """

    def __init__(self, dependency: object, interval_ms: int = 1000, ticks: object | None = None) -> None:
        self._dep = dependency
        self._interval_ms = interval_ms
        if ticks is not None:
            self._ticks_diff = ticks.ticks_diff
            self._ticks_add = ticks.ticks_add
            self._next_ms = ticks.ticks_ms()
        else:
            from chumicro_timing import ticks_diff, ticks_add, ticks_ms
            self._ticks_diff = ticks_diff
            self._ticks_add = ticks_add
            self._next_ms = ticks_ms()

    def check(self, now_ms: int) -> bool:
        """Return True if the service should act this tick.

        Args:
            now_ms: Current time in milliseconds.

        Returns:
            True if the interval has elapsed.
        """
        if self._ticks_diff(now_ms, self._next_ms) < 0:
            return False
        self._next_ms = self._ticks_add(now_ms, self._interval_ms)
        return True

    def handle(self, now_ms: int) -> None:
        """Perform the service action.

        Args:
            now_ms: Current time in milliseconds.
        """
        # ... do work ...
```

Wire into Runner:

```python
from chumicro_runner import Runner

runner = Runner(ticks=fake_ticks)  # or Runner() for real clock
runner.add(service)  # Runner calls service.check(), then service.handle()
# ... or use callables:
runner.add(service.check, handler=some_function)
# ... or periodic without a check gate:
runner.add_periodic(handler, period_ms=100)
```

Existing example: `Heartbeat` does not implement `check`/`handle`
(it predates the Runner), but it demonstrates the constructor
injection and `ticks` protocol patterns that Runner-compatible
services should follow.

Related: Decision 0014, `libraries/runner/src/chumicro_runner/core.py`.

## Constructor injection

Accept dependencies (time, I/O, network) as constructor parameters.  Never
import hardware modules at the top level of library code (Decision 0010).
Use a lazy import in the `else` branch so the module only loads when no
fake is provided.

```python
# ✅ Injectable — testable with fakes, lazy hardware import
class Sensor:
    """Hardware sensor with injectable I2C and tick dependencies."""

    def __init__(self, i2c: object | None = None, ticks: object | None = None) -> None:
        if i2c is not None:
            self._i2c = i2c
        else:
            import board, busio
            self._i2c = busio.I2C(board.SCL, board.SDA)
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms
            self._ticks_ms = ticks_ms
```

```python
# ❌ Hard-wired — untestable, fails on CPython
import board
import busio

class Sensor:
    def __init__(self) -> None:
        self._i2c = busio.I2C(board.SCL, board.SDA)
```

Existing examples: `Heartbeat(ticks=None)` and `Runner(ticks=None)`
both use this exact pattern — accept an optional ticks object, fall
back to a lazy import of the real module.

Related: Decision 0010, `libraries/timing/src/chumicro_timing/heartbeat.py`.

## Test fakes as `testing` submodules

Ship fakes alongside production code in `src/chumicro_<name>/testing.py`.
Downstream libraries import them directly (Decision 0010).

```python
# In src/chumicro_mylib/testing.py
class FakeBackend:
    """Test fake for Backend protocol.

    Provides call recording and deterministic behavior for tests.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read(self) -> bytes:
        """Return an empty response and record the call."""
        self.calls.append("read")
        return b""
```

```python
# In downstream tests
from chumicro_mylib.testing import FakeBackend
```

If the library has nothing worth faking, delete `testing.py` and its
references (see `new-library` skill § 4).

Related: Decision 0010, `new-library` skill.

## Cross-runtime shim

When a module exists on CPython but not on MicroPython/CircuitPython
(or vice versa), write a thin shim with runtime detection.

```python
try:
    from micropython import const
except ImportError:
    def const(value: int) -> int:
        """Identity fallback so const() works on CPython."""
        return value
```

For larger differences (e.g., `socketpool` vs `socket`), create a
dedicated shim module that detects the runtime and re-exports a
consistent API.  Keep function names aligned with CPython's stdlib.

Related: `libraries/compat/`, Decision 0007.

## Backend protocol (duck-typed)

When a library needs swappable implementations (storage backends,
transport layers), define the protocol as documentation — not as an
ABC.  Implementations duck-type the interface.

The ticks injection in `chumicro-timing` is the existing example:
`Heartbeat(ticks=obj)` and `Runner(ticks=obj)` accept any object
with `ticks_ms()`, `ticks_diff()`, and `ticks_add()` methods.
`FakeTicks` duck-types this protocol for tests.  The protocol is
documented in the constructor docstring, not enforced by a base class.

For libraries that need storage or I/O backends (e.g., the planned
settings library), apply the same approach:

```python
# Document the protocol in the constructor docstring:
#
#   backend must implement:
#     read() -> bytes    — return stored data
#     write(data) -> None — persist data
#
# Implementations: NvmBackend, FileBackend, MemoryBackend

class Settings:
    """Key-value settings backed by a pluggable storage backend."""

    def __init__(self, backend: object, defaults: dict[str, object] | None = None) -> None:
        self._backend = backend
        # ...
```

Provide a `MemoryBackend` or similar in-memory implementation for
tests.  Ship it in `testing.py`.

Existing examples:
- `chumicro_timing.testing.FakeTicks` — duck-types the ticks protocol
- `chumicro_runner.testing.CallRecorder` — duck-types the handler callable

Related: Decision 0010 (don't mock what you don't own), settings
library design in `next-up.md`.

## Per-library test isolation

Each library's tests run in a separate pytest subprocess.  Coverage is
measured per-library with a coverage gate (Decision 0009, threshold in `pyproject.toml`).

```bash
# Run one library
python scripts/run.py test --libraries timing

# Quick iteration — no coverage, stop on first failure
python scripts/run.py test -k timing/test_heartbeat -x -v --no-cov
```

Never run bare `pytest` from the repo root.  The test runner sets
PYTHONPATH and coverage configuration automatically.

Related: Decision 0009, `debug-test-failure` skill.

