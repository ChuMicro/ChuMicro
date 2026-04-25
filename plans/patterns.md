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

**Per-package fakes, not a shared abstractions package:** Each package
owns its own test fakes in its `testing.py` submodule.  Cross-package
sharing would require either a published support package (extra release
overhead) or duplicating ~80 lines per consumer — and since the only
fakes that recur are tiny, duplication beats the abstraction tax.

Concrete examples in the workspace today:

- `chumicro_timing.testing.FakeTicks` — millisecond-tick fake used by
  the timing library and re-imported by `chumicro_runner` tests.
- `chumicro_deploy.testing.FakeTime` — seconds-domain time fake for
  `CircuitpythonTransport`'s injectable time source; lives next to
  `FakeTransport` and `FakeSerialPort` so a downstream `pip install
  chumicro-deploy` user gets a complete test-fakes set.

These are different fakes for different domains (ms-tick on device vs
seconds-monotonic on host), not two implementations of one thing.  If
a future package needs seconds-domain on device, it copies the ~80
lines into its own `testing.py` rather than introducing a shared
abstractions package.

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

Related: Decision 0010 (prefer provided fakes over ad-hoc mocks), settings
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

## mpremote internals we depend on

`MicropythonTransport` is a thin layer over the vendored
`mpremote.transport_serial.SerialTransport`.  Several behaviours of
that class are undocumented upstream and have bitten us before — they
are captured here so future edits do not unwittingly re-break them.

### 1. `exec_raw` returns a tuple, not bytes

```python
stdout_bytes, stderr_bytes = serial_transport.exec_raw(code)
```

`SerialTransport.exec_raw` returns a `(stdout, stderr)` tuple of
`bytes`, not a single `bytes` object.  `MicropythonTransport.execute()`
unpacks both halves, decodes each, and concatenates stdout + stderr so
tracebacks surface in the captured output.  A belt-and-suspenders
`isinstance(result, bytes)` branch is kept for future mpremote API
drift.  Commit `41f5391`.

### 2. `mount_local` wraps every call

Calling `SerialTransport.mount_local(...)` wraps `self.serial` in a
`SerialIntercept` **every time it's invoked** — not idempotently.  A
second call produces `SerialIntercept(SerialIntercept(raw))` and
corrupts every subsequent I/O (even a bare `import` fails).

Invariants:

- `umount_local` must run *before* any Ctrl-D soft-reset — after
  the reset, the device globals are gone, and a later `umount_local`
  would try to run `os.umount(...)` with `os` no longer imported.
- `soft_reset()` does not re-mount.  The mount is owned by
  `stage()`, which is the next orchestration step and re-mounts
  once cleanly.

Commit `5698100`.

### 3. Don't `mpremote reset` between test batches

`mpremote reset` cycles the USB stack on the board.  The next
`mpremote` invocation then connects before the port is ready and
fails with `"Device not configured"`.  mpremote already spawns a
fresh subprocess per `exec_raw()` call, so test isolation is
automatic on the MicroPython path — `soft_reset()` is a
CircuitPython-only operation (both RAM and flash modes) where the
persistent raw-REPL session would otherwise accumulate modules in
`sys.modules` across calls.  Commit `cd9fe3b`.

### 4. Hold one `SerialTransport` per session

Creating a fresh mpremote subprocess per file costs ~2–3 s on most
boards — the floor is the serial connect handshake, not the actual
`exec`.  `MicropythonTransport` keeps a single
`SerialTransport` instance alive across the session and routes
every `execute()` through it.  Combined with bulk rsync (one pass
for all files, not per-file), this brought the "per MP test file"
floor from seconds to milliseconds.  Commits `9e6174c` + `cb4efa9`.

Related: Decision 0027 (device testing infrastructure), Decision 0028
(deploy modes).

## Subprocess binary resolution (host tools)

When a host-side tool shells out to an installable CLI binary
(`mpremote`, `esptool`, `rshell`, future `ampy`), resolve the binary
by the running interpreter's sibling `bin/` first, not by a bare
name on `PATH`:

```python
import shutil
import sys
from pathlib import Path

def _resolve_binary(name: str) -> str:
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    located = shutil.which(name)
    if located:
        return located
    return name  # last-resort — let the subprocess error surface
```

**Why:** PyCharm and VS Code launch test runs via the interpreter
path without activating a shell, so `.venv/bin` is not on `PATH`
even on a freshly prepared workspace.  A bare `"mpremote"` in an
argv list fails with
`[Errno 2] No such file or directory: 'mpremote'` on that code
path while the same command works fine from an activated terminal.
Resolving next to `sys.executable` makes `.venv/bin/mpremote` the
primary candidate, `shutil.which` handles system-wide installs and
Windows `Scripts/mpremote.exe`, and the bare-name fallback preserves
the subprocess-level error message when nothing resolves.

Only the first element of the argv list changes — the rest of the
command stays identical.  `MicropythonTransport._run_mpremote`
implements this pattern; apply it to any future shell-out.  Commit
`e4f669e`.

## Lazy module-level imports via PEP 562 `__getattr__` (workbench)

**Workbench-only in practice.**  PEP 562's `module __getattr__` is
implemented at the firmware level on both MP and CP (verified in
the pinned source — `MICROPY_MODULE_GETATTR` default-on at the
`CORE_FEATURES` ROM level), but the **deploy harness's
CircuitPython RAM-mode path wraps the package in a class-as-module
stub that silently bypasses PEP 562**.  Lookups hit the stub's
`__dict__` directly without calling `__getattr__`, so the lazy attr
table just doesn't fire.  MP + the unix-ports both honor PEP 562
correctly; only CP RAM-mode is affected — but that's the
canonical deploy path for chumicro libraries.

The pattern is **safe for workbench packages** (`chumicro-deploy`,
`chumicro-repl`) because they're CPython-only.  For device
libraries (anything under `libraries/*/src/`), use per-function
lazy imports instead — see "Per-function lazy adapter selection"
below, which works everywhere.

History: surfaced 2026-04-25 during chumicro-wifi Slice 0
hardware bring-up; lifted to `plans/learnings.md` and the
lazy-loading research doc.  The earlier "cross-runtime by design"
framing was correct at the firmware level but missed the harness
wrapper.

When a package has multiple submodules where users typically reach
for a subset, defer submodule imports until first attribute access:

```python
# In src/chumicro_<name>/__init__.py — minimum shape.
def __getattr__(name: str) -> object:
    if name == "Deployer":
        from chumicro_deploy.deployer import Deployer
        return Deployer
    if name == "Device":
        from chumicro_deploy.device import Device
        return Device
    raise AttributeError(f"module 'chumicro_deploy' has no attribute {name!r}")
```

For libraries with more than ~5 lazy attributes, prefer the
**`_LAZY_ATTRS` dict + `__getattr__` table** shape used in
`chumicro_deploy/__init__.py:94`:

```python
_LAZY_ATTRS: dict[str, str] = {
    "Deployer": "deployer",      # public name -> submodule name
    "Device":   "device",
    # ...
}

__all__ = [...]   # literal list so static type checkers see it
assert sorted(__all__) == __all__, "__all__ must be alphabetized"
assert set(__all__) == set(_LAZY_ATTRS), "__all__ must match _LAZY_ATTRS"


def __getattr__(name: str) -> object:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value     # cache so subsequent accesses are O(1)
    return value


def __dir__() -> list[str]:
    return [*globals().keys(), *_LAZY_ATTRS.keys()]
```

A `TYPE_CHECKING`-guarded import block above the table preserves
static-analysis support (pyright sees every name; runtime resolution
still goes through the lazy hook).  The `__dir__` shadow keeps
introspection tools (`dir()`, REPL completion) working.

**When to use this pattern (Tier B libraries):**

- Per-runtime adapters under `_adapters/` or `_backends/` (the kvstore
  template) — adopt for any library that ships >1 adapter and selects
  one at construction.
- Optional features the user may never reach for.
- ~5+ public attributes spread across submodules.

**When eager imports are correct:** small-surface libraries (≤2
modules, no per-runtime adapters), tightly-coupled submodules
(`chumicro-timing` always uses both `heartbeat` and `ticks`), and
hot-path code where lazy first-use overhead would show up as a tick
spike.  See `plans/workstreams/lazy-loading-research.md` for the
full Tier A vs Tier B classification.

Existing names (e.g. `from chumicro_deploy import Deployer`) keep
working — Python's attribute lookup falls through to `__getattr__`
after the module's own globals are exhausted.  The deferred imports
run once on first access; subsequent accesses are O(1) via the
`globals()[name] = value` cache.

Applied to `chumicro_deploy/__init__.py` and
`chumicro_repl/__init__.py` (commits `11952f0` workbench review-
sweep).  `chumicro-deploy`'s `device.py` defers transport imports
into `create_transport()` for the same reason; `chumicro-kvstore`'s
`_select_backend` does the equivalent for runtime adapter
selection.

Related: lazy-loading-research workstream, Decision 0010
(constructor injection — same "defer the cost" philosophy at the
class-instance scope).

## Per-function lazy adapter selection (cross-runtime safe)

Use this for **device libraries with per-runtime adapters** —
the cross-runtime-safe alternative to module-level PEP 562 (which
the CP RAM-mode harness silently bypasses, see the section above).
Goes inside a selector function the user reaches via construction:

```python
# In src/chumicro_<name>/service.py (or wherever the selector lives)
import sys

from chumicro_<name>._adapters.fake import FakeAdapter   # eager; the host fallback
from chumicro_<name>._adapters.base import BaseAdapter   # eager; the protocol


def _select_adapter():
    """Pick the runtime-appropriate adapter at construction time."""
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_<name>._adapters.cp import CpAdapter
        return CpAdapter()
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        try:
            import esp32  # noqa: F401
        except ImportError:
            from chumicro_<name>._adapters.mp_rp2 import MpRp2Adapter
            return MpRp2Adapter()
        from chumicro_<name>._adapters.mp_esp32 import MpEsp32Adapter
        return MpEsp32Adapter()
    return FakeAdapter()
```

**Why this works on every runtime where module ``__getattr__``
doesn't:** the named ``from X import Y`` statement inside the
function body is compiled into the runtime's standard import
machinery — invoked once when the function runs, resolved via the
package loader the harness already understands.  The class-as-
module wrapper that breaks PEP 562 doesn't sit between the user
and an explicit submodule import.

**`# pragma: no cover` for the CP / MP branches:** they can't be
exercised from CPython tests; coverage is instead provided by the
per-runtime functional suites that exist for each adapter.  Test
the *selection* logic with a `monkeypatch.setattr(sys, ...)` test
or by injecting a concrete adapter via the public constructor's
`adapter=` kwarg.

**Adopted by:** `chumicro_kvstore._select_backend` (4 backends),
`chumicro_wifi.service._select_adapter` (4 adapters,
hardware-verified Phase 3a Slice 0).  Future libraries with
adapter sets (sockets, mqtt, sensor drivers) follow the same
shape.

Related: lazy-loading-research workstream §"Cross-runtime support",
Decision 0010 (constructor injection lets tests bypass the
selector entirely via injected fakes).

## StrEnum as a backwards-compatible shim for stringly-typed args

When a parameter has historically accepted plain strings (`Device(transport="circuitpython")`) and you want to introduce an enum without breaking every call site, use `enum.StrEnum`. StrEnum members compare equal to their string value, so existing string literal call sites keep working unchanged while new code can use the enum for autocomplete + typo prevention.

```python
from enum import StrEnum

class Runtime(StrEnum):
    MICROPYTHON = "micropython"
    CIRCUITPYTHON = "circuitpython"

# Old call site (still works):
Device(transport="circuitpython")

# New call site (preferred):
Device(transport=Runtime.CIRCUITPYTHON)

# Both compare equal:
assert Runtime.CIRCUITPYTHON == "circuitpython"
```

Applied to `Runtime` / `DeployMode` / `ReflashMethod` in `chumicro_deploy/protocol.py` (commit `11952f0`).

Caveats: `StrEnum` is Python 3.11+ stdlib. For older Pythons or for embedded code, this pattern doesn't apply — `chumicro-deploy` is workbench-only (CPython 3.11+) so it's safe there. Do not use this on `libraries/` code that targets CircuitPython / MicroPython.

## IDE Testing-panel "show-but-deselect" for hardware-gated tests

When you have hardware-gated tests under a path like `functional_tests/` that should be:

- **invisible** in the IDE Testing panel for fresh clones (no devices configured),
- **visible** in the IDE Testing panel once `devices.yml` exists, so the gutter ▶ button works on individual test functions,
- **never run** in a default sweep (`pytest` from rootdir, "Run All Tests" in IDE), because they touch real hardware,
- **fully run** when the user explicitly clicks gutter ▶ on a single test or names a `functional_tests/` path on the command line.

Pattern: a paired `pytest_ignore_collect` + `pytest_collection_modifyitems` in the root `conftest.py`.

```python
# Allow collection only when (a) devices.yml exists, or (b) the user explicitly
# named a functional_tests path in argv.
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if "functional_tests" not in collection_path.parts:
        return None
    if _devices_yml_exists() or _explicit_functional_target(config):
        return False  # allow
    return True       # hide

# Even when collected, deselect functional_tests items unless an explicit
# functional_tests/ path is in argv.
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _explicit_functional_target(config):
        return
    deselected = [item for item in items if "functional_tests" in Path(item.fspath).parts]
    if deselected:
        for item in deselected:
            items.remove(item)
        config.hook.pytest_deselected(items=deselected)
```

Result: VS Code / PyCharm Testing panels paint the tree with gutter ▶ buttons on every functional test the user can see in `devices.yml`. Bare `pytest` from rootdir does host tests only. Click ▶ on one test → its path lands in argv → deselection skipped → run executes against the device. Commit `73e9270`.

Related: Decision 0027, `scripts/pytest_device.py` plugin (which owns the actual device routing once a functional test is selected).

