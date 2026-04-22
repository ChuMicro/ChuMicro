# Adding a New Library

This guide walks you through the full lifecycle of adding a new library to ChuMicro — from idea to published package. If you're working with an AI agent, point it at the [`new-library` skill](../../.github/skills/new-library/SKILL.md).

## Before you start

Check [open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions), and skim [`plans/roadmap.md`](../../plans/roadmap.md) and [`plans/decisions/`](../../plans/decisions/) to see if your idea overlaps with planned work or settled design choices. If you're unsure whether the library fits the project, open a discussion first — it's much faster to align on scope before building.

> **Is your package host-only?**  This guide is for *device libraries* — code that runs on CircuitPython, MicroPython, and CPython.  If you're adding a tool that runs only on the developer's laptop (a CLI that drives devices, a REPL client, a firmware helper), it belongs in `workbench/` instead.  See [`workbench.md`](workbench.md) for the layout and conventions — the scaffolder does not yet create workbench packages, so for now you hand-roll the layout off this guide as a template.

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
│   ├── api.md                       # API reference (mkdocstrings renders it)
│   └── testing.md                   # testing helpers docs
├── examples/
│   └── quickstart.py                # working example using MyThing
└── functional_tests/
    └── .gitkeep                     # on-device tests live here
```

In addition to creating the library directory, the scaffolder runs an editable install (`pip install -e libraries/my-thing`) and re-runs `sync-ide`, which updates the local `.idea/chumicro.iml` plus the tracked `.idea/runConfigurations/`, `pyrightconfig.json`, `.vscode/tasks.json`, and `.vscode/settings.json` so your IDE picks up the new package immediately. The `.iml` stays local and gitignored because PyCharm may rewrite it while the project is open; the tracked config files are the ones you may see in `git status` after running `new-library`.

The scaffold is immediately runnable — tests pass at 100% coverage, lint is clean, and the example executes. Start by replacing the starter `MyThing` class in `core.py` with your real implementation.

## 2. Implement

Put your code in `src/chumicro_my_thing/`. Follow the [Style Guide](style-guide.md) for naming, annotations, docstrings, and formatting. Key rules for library code:

- **No `async`/`await`** — use the tick-based runner pattern. If your library has active components, implement `check(now_ms) -> bool` so they work with [`Runner`](../../libraries/runner/).
- **No third-party dependencies** that aren't available on all three runtimes.
- **No `typing` imports** — use PEP 604/585 syntax: `int | None`, `list[int]`.
- **Memory patterns are optional on day one** — `const()`, `memoryview`, pre-allocated buffers. Focus on correctness first. The [Style Guide](style-guide.md#memory-patterns-library-code-only) has the full list when you're ready.

### Constructor injection

Accept dependencies (time sources, I/O objects, network sockets) as constructor parameters instead of importing hardware modules at the top level. This makes your code testable without real hardware:

```python
# ✅ Good — testable, injectable
class MySensor:
    """Reads from a sensor on a schedule."""

    def __init__(self, i2c: object, interval_ms: int = 1000) -> None:
        self._i2c = i2c
        self._interval_ms = interval_ms
```

```python
# ❌ Bad — hard-wired to hardware, can't test without a board
import board
import busio

class MySensor:
    def __init__(self) -> None:
        self._i2c = busio.I2C(board.SCL, board.SDA)
```

See [Decision 0010](../../plans/decisions/0010-library-testability.md) for the reasoning.

### Public API

Export your public API from `__init__.py`:

```python
"""ChuMicro my-thing — one-line description."""

from chumicro_my_thing.core import MyClass, helper_function

__all__ = ["MyClass", "helper_function"]
```

## 3. Write tests

Tests go in `libraries/my-thing/tests/`. Every library must independently meet the coverage threshold configured in `pyproject.toml`.

```bash
python scripts/run.py test --libraries my-thing

# Quick iteration (skip coverage, stop on first failure)
python scripts/run.py test -k my-thing/test_core -x -v --no-cov
```

### What a test looks like

Since you accepted dependencies as constructor parameters, testing is straightforward — pass in a fake:

```python
"""Tests for MySensor reading behavior."""

from chumicro_my_thing import MySensor


class FakeI2C:
    """Fake I2C bus that returns predetermined data."""

    def __init__(self, data: list) -> None:
        self._data = data
        self.read_count = 0

    def readfrom_into(self, address: int, buffer: bytearray) -> None:
        """Fill buffer with the next predetermined response."""
        buffer[:] = self._data[self.read_count]
        self.read_count += 1


def test_sensor_reads_from_bus() -> None:
    """Sensor returns data from the I2C bus."""
    fake_i2c = FakeI2C(data=[b"\x01\x02"])
    sensor = MySensor(fake_i2c, interval_ms=100)

    result = sensor.read()
    assert result == b"\x01\x02"
```

Create lightweight fakes for your own interfaces. Use fakes from upstream ChuMicro libraries when available (`from chumicro_timing.testing import FakeTicks`). `unittest.mock` is fine when a purpose-built fake doesn't exist or doesn't make sense — but with dependency injection, you'll usually find that a simple fake gives better test control than patching.

### Testing submodule

If downstream libraries or users would benefit from test fakes, keep `src/chumicro_my_thing/testing.py` and implement real fakes. If there's nothing worth faking, delete it and its references:

1. Delete `src/chumicro_my_thing/testing.py`
2. Delete `docs/testing.md`
3. Remove `- Testing Helpers: testing.md` from `mkdocs.yml`
4. Remove the Testing Helpers link from `docs/index.md`
5. Remove the Testing Helpers link from `README.md`

### Functional tests on real boards

Every new library scaffold also includes `functional_tests/` for behavior that needs a real board. You do **not** need to fill this directory immediately, but if the library has timing-, transport-, GPIO-, or storage-sensitive behavior, plan to add real-board tests here once the host/unit tests are stable.

Run them with:

```bash
python scripts/run.py setup
python scripts/run.py test-device --library my-thing
```

See [Device Testing](device-testing.md) for `devices.yml`, deploy modes, and IDE play-button behavior.

## 4. Write docs

### User guide (`docs/guide.md`)

Replace the placeholder with a real guide covering:

1. **Overview** — what the library does and when to use it
2. **Installation** — circup, mip, and pip commands
3. **Quick start** — minimal working example
4. **API walkthrough** — main classes and functions with examples
5. **Cross-runtime notes** — any behavior differences across runtimes

```bash
python scripts/run.py docs --libraries my-thing
```

### API reference (`docs/api.md`)

mkdocstrings renders API docs from your docstrings. The scaffold starts with a single directive — add section headings and per-module directives as you add modules. See `libraries/timing/docs/api.md` for an example.

Every public function, method, and class needs a docstring. Types go on the signature as annotations; docstrings carry descriptions only:

```python
def ticks_diff(end: int, start: int) -> int:
    """Signed difference between two tick values.

    Args:
        end: Later tick value.
        start: Earlier tick value.

    Returns:
        Signed difference in milliseconds.
    """
```

See the [Style Guide](style-guide.md#docstrings) for the full format.

## 5. Write examples

Put examples in `libraries/my-thing/examples/`. Rules:

- **Top-level code** — no `if __name__ == "__main__":` guard
- **Descriptive filenames** — `sensor_basic_reading.py`, not `example1.py`
- **Module docstring** with an `Example output::` block
- **Self-contained** — copy-paste and run
- **Hardware examples** — prefix with `circuitpython_` or `micropython_`

```bash
python scripts/run.py verify-examples --libraries my-thing
```

## 6. Fill in metadata

Update `libraries/my-thing/pyproject.toml`:

- `description` — one-line package description
- `dependencies` — if your library depends on other ChuMicro libraries (e.g., `"chumicro-timing>=0.1"`)

Update `libraries/my-thing/README.md` — replace all TODO placeholders.

The README template now includes a short development/testing section. Keep it accurate for the library you are adding so contributors can see the host-test and device-test entry points without hunting through the repository docs.

## 7. Preflight and PR

```bash
python scripts/run.py preflight
```

Must print `Preflight passed`. Then push and open a PR on GitHub targeting `main`. See [Creating a Pull Request](pull-requests.md) for the full walkthrough.

## 8. After merge

When your PR merges, the VERSION bump triggers an automatic **experimental release**:

- Your package is published to PyPI as `chumicro-my-thing-experimental`
- Files are pushed to the [experimental bundle repo](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
- Experimental docs are deployed
- A git tag `my-thing-v0.1.0-experimental` is created

Users can install your library immediately:

```bash
# CircuitPython
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-my-thing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_my_thing

# CPython
pip install chumicro-my-thing-experimental
```

When you're confident the experimental release is production-ready, open a [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) and a maintainer will promote it. See [Releases](releases.md) for details.

## Checklist

- [ ] `python scripts/run.py new-library <name>` — scaffold created
- [ ] Implementation in `src/chumicro_<name>/`
- [ ] Public exports in `__init__.py` with `__all__`
- [ ] Tests in `tests/` — coverage gate passing
- [ ] Testing submodule: kept and implemented, or deleted with all references
- [ ] Examples in `examples/` — `verify-examples` passes
- [ ] `docs/guide.md` — real content, no placeholders
- [ ] `README.md` — description and API summary filled in
- [ ] `pyproject.toml` — description and dependencies set
- [ ] Preflight passes
- [ ] PR opened and CI green
