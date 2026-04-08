# Adding a New Library

This guide walks you through the full lifecycle of adding a new library to Chumicro — from idea to published package. It's written for humans; if you're working with an AI agent, point it at the [`new-library` skill](../../.github/skills/new-library/SKILL.md) for the condensed version.

## Overview

```mermaid
flowchart LR
    A[Scaffold] --> B[Implement]
    B --> C[Test<br/>94% coverage]
    C --> D[Docs &<br/>examples]
    D --> E[Preflight]
    E --> F[Open PR]
    F --> G[CI + review]
    G --> H[Merge]
    H --> I[Experimental<br/>release]
    I --> J[Request stable<br/>promotion]
    J --> K[Stable<br/>release]
```

## 1. Scaffold

```bash
python scripts/run.py new-library my-thing
```

This creates `libraries/my-thing/` with:

```
libraries/my-thing/
├── VERSION                          # starts at 0.1.0
├── pyproject.toml                   # package metadata
├── README.md                        # package README (fill in TODOs)
├── mkdocs.yml                       # docs config
├── src/chumicro_my_thing/
│   ├── __init__.py                  # public exports (imports MyThing)
│   ├── core.py                      # starter class with patterns
│   └── testing.py                   # test fakes (keep or delete)
├── tests/
│   ├── conftest.py                  # pytest config
│   └── test_my_thing.py             # starter tests (100% coverage)
├── docs/
│   ├── index.md                     # docs landing page
│   ├── guide.md                     # user guide (fill in)
│   ├── api.md                       # API reference (mkdocstrings renders it; curate sections as you add modules)
│   └── testing.md                   # testing helpers docs
├── examples/
│   └── quickstart.py                # working example using MyThing
└── functional_tests/                # on-device tests
```

The scaffold is immediately runnable — tests pass at 100% coverage, lint is clean, and the example executes.  Start by replacing the starter `MyThing` class in `core.py` with your real implementation.

## 2. Implement

Put your code in `src/chumicro_my_thing/`. The rules for library code:

### Cross-runtime compatibility

Your code must work on CircuitPython, MicroPython, *and* CPython. This means:

- **No `async`/`await`** — use the tick-based runner pattern. If your library has active components, implement `check(now_ms) -> bool` so they work with [`Runner`](../../libraries/runner/).
- **No third-party dependencies** that aren't available on all three runtimes. If a library doesn't support CircuitPython, re-implement the functionality.
- **No type annotations on function signatures** — CircuitPython and MicroPython don't reliably support them. Document types in docstrings instead.

### Constructor injection

Accept dependencies (time sources, I/O objects, network sockets) as constructor parameters. Don't import hardware modules at the top level.

```python
# ✅ Good — injectable, testable
class MySensor:
    """Reads from a sensor on a schedule.

    Args:
        i2c (busio.I2C): I2C bus instance.
        interval_ms (int): Read interval in milliseconds.
    """

    def __init__(self, i2c, interval_ms=1000):
        self._i2c = i2c
        self._interval_ms = interval_ms
```

```python
# ❌ Bad — hard-wired to hardware
import board
import busio

class MySensor:
    def __init__(self):
        self._i2c = busio.I2C(board.SCL, board.SDA)  # untestable
```

Why? So tests can inject fakes without touching real hardware. See [Decision 0010](../../plans/decisions/0010-library-testability.md).

### Memory-efficient patterns

Library code runs on boards with as little as 256 KB RAM:

- **Pre-allocate buffers** in the constructor, reuse with `readinto()`
- **Use `memoryview`** for slicing — avoids copies
- **Use `const()`** for numeric constants (import from `micropython`)
- **Use f-strings** for all string formatting
- **Don't build strings in loops**

These patterns are required in `libraries/` code. They are *not* required in `scripts/` or `support/` (those only run on CPython).

### Public API

Export your public API from `__init__.py`:

```python
"""Chumicro my-thing — one-line description."""

from chumicro_my_thing.core import MyClass, helper_function

__all__ = ["MyClass", "helper_function"]
```

## 3. Write tests

Tests go in `libraries/my-thing/tests/`. The coverage gate is **94%** — every library must meet it independently.

```bash
# Run tests for your library
python scripts/run.py test --libraries my-thing

# Quick iteration (skip coverage, stop on first failure)
python scripts/run.py test -k my-thing/test_core -x -v --no-cov
```

### What good tests look like

```python
"""Tests for MySensor reading behavior."""

from chumicro_my_thing import MySensor


class FakeI2C:
    """Fake I2C bus that returns predetermined data."""

    def __init__(self, data):
        self._data = data
        self.read_count = 0

    def readfrom_into(self, addr, buf):
        """Fill buf with the next predetermined response."""
        buf[:] = self._data[self.read_count]
        self.read_count += 1


def test_sensor_reads_on_interval():
    """Sensor returns data from the I2C bus."""
    fake_i2c = FakeI2C(data=[b"\x01\x02"])
    sensor = MySensor(fake_i2c, interval_ms=100)

    result = sensor.read()
    assert result == b"\x01\x02"
    assert fake_i2c.read_count == 1
```

Key principles:

- **Fake what you own, don't mock what you don't.** Create lightweight fakes for your own interfaces. Use fakes from upstream Chumicro libraries (`from chumicro_timing.testing import FakeTicks`). Don't use `unittest.mock` on third-party APIs.
- **Test behavior, not implementation.** Assert on outputs and side effects, not internal state.
- **Constructor injection makes this easy.** Since you accepted dependencies as parameters, pass in fakes.

### Testing submodule

If downstream libraries or users would benefit from test fakes for your library, keep `src/chumicro_my_thing/testing.py` and implement real fakes. If there's nothing worth faking, delete it and its references:

1. Delete `src/chumicro_my_thing/testing.py`
2. Delete `docs/testing.md`
3. Remove `- Testing Helpers: testing.md` from `mkdocs.yml`
4. Remove the Testing Helpers link from `docs/index.md` and `README.md`

## 4. Write docs

### User guide (`docs/guide.md`)

Replace the placeholder with a real guide. Required sections:

1. **Overview** — what the library does and when to use it
2. **Installation** — circup, mip, and pip commands
3. **Quick start** — minimal working example
4. **API walkthrough** — explain the main classes and functions with examples
5. **Cross-runtime notes** — any behavior differences across CircuitPython/MicroPython/CPython

```bash
# Build docs
python scripts/run.py docs --libraries my-thing

# Live preview
python scripts/run.py docs --libraries my-thing --serve
```

### API reference (`docs/api.md`)

mkdocstrings renders API docs from your docstrings — the scaffold starts with a single `::: chumicro_my_thing` directive that covers the starter class. As you add modules, add section headings and per-module directives (e.g., `::: chumicro_my_thing.core`). See `libraries/timing/docs/api.md` for an example.

Every public function, method, and class needs a Google-style docstring:

```python
def ticks_diff(end, start):
    """Compute the signed difference between two tick values.

    Handles wraparound correctly for values from ``ticks_ms()``.

    Args:
        end (int): The later tick value.
        start (int): The earlier tick value.

    Returns:
        int: Signed difference in milliseconds. Positive if ``end``
            is after ``start``.

    Raises:
        OverflowError: If the difference exceeds the tick range.
    """
```

## 5. Write examples

Put examples in `libraries/my-thing/examples/`. Rules:

- **Top-level code** — no `if __name__ == "__main__":` guard
- **Descriptive filenames** — `sensor_basic_reading.py`, not `example1.py`
- **Module docstring** with an `Example output::` block
- **Self-contained** — copy-paste and run
- **Hardware examples** — prefix with `circuitpython_` or `micropython_`

```bash
# Verify examples parse correctly
python scripts/run.py verify-examples --libraries my-thing
```

## 6. Fill in metadata

Update `libraries/my-thing/pyproject.toml`:

- `description` — one-line package description
- `dependencies` — if your library depends on other Chumicro libraries (e.g., `"chumicro-timing>=0.1"`)

Update `libraries/my-thing/README.md` — replace all TODO placeholders.

## 7. Run preflight

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

Must show:

```
Preflight passed — required CI checks should pass.
```

Preflight runs everything CI runs: lint, tests (94% coverage), docs build, example verification, version check, API check, and cross-runtime compatibility.

## 8. Open your PR

```bash
git push -u origin feature/my-thing-library
```

Open a PR on GitHub targeting `main`. CI runs automatically. See [Creating a Pull Request](pull-requests.md) for the full walkthrough.

## 9. After merge — experimental release

When your PR merges, the VERSION bump triggers an automatic experimental release:

- PyPI: `chumicro-my-thing-experimental` package published
- Bundle: files pushed to `ChuMicro-Bundle-Experimental`
- Docs: experimental docs deployed
- Git tag: `my-thing-v0.1.0-experimental` created

Users can install immediately:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-my-thing
```

## 10. Stable promotion

When you're confident the experimental release is production-ready:

1. Open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) issue
2. A maintainer runs `promote.yml` from the experimental tag
3. The library is published as a stable release — `chumicro-my-thing` on PyPI, `ChuMicro-Bundle`, and stable docs

See [Releases](releases.md) for the full release model.

## Checklist

Use this to track your progress:

- [ ] `python scripts/run.py new-library <name>` — scaffold created
- [ ] Implementation in `src/chumicro_<name>/`
- [ ] Public exports in `__init__.py` with `__all__`
- [ ] Tests in `tests/` — 94% coverage passing
- [ ] Testing submodule: kept and implemented, or deleted with all references
- [ ] Examples in `examples/` — `verify-examples` passes
- [ ] `docs/guide.md` — real content, no placeholders
- [ ] `README.md` — description and API summary filled in
- [ ] `pyproject.toml` — description and dependencies set
- [ ] Preflight passes
- [ ] PR opened and CI green

