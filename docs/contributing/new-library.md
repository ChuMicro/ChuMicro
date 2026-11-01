# Adding a New Library

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

An AI agent adding a library follows the [`new-library` skill](https://github.com/ChuMicro/ChuMicro/tree/main/.github/skills/new-library/SKILL.md).

<br clear="left">

> **A laptop-only tool**, such as a CLI that drives devices, a REPL client, or a firmware helper, belongs in `workbench/`, and [Adding a Workbench Package](workbench.md) covers it. A *device library*, code that runs on CircuitPython, MicroPython, and CPython, follows the steps here.

## Before you start

Check [open issues](https://github.com/ChuMicro/ChuMicro/issues) and [discussions](https://github.com/ChuMicro/ChuMicro/discussions), and skim [`plans/next-up.md`](https://github.com/ChuMicro/ChuMicro/blob/main/plans/next-up.md) and [`plans/decisions/`](https://github.com/ChuMicro/ChuMicro/tree/main/plans/decisions/), for planned work or settled design choices that overlap your idea. When the library's fit is unclear, open a discussion first: agreeing on scope before building saves rework.

## 1. Scaffold

```bash
python scripts/run.py new-library my_sensor
```

`new-library` renders the library from `chumicro-workspace`'s scaffold templates, then installs it in editable mode and re-runs `sync-ide`. Outside this repository, a workspace runs the same scaffolder with `python3 run.py new --library <name>`.

The scaffold creates `libraries/my_sensor/`:

```
libraries/my_sensor/
├── VERSION                          # starts at 0.1.0
├── pyproject.toml                   # package metadata
├── README.md                        # package README (rewrite the worked example)
├── mkdocs.yml                       # docs config
├── src/chumicro_my_sensor/
│   ├── __init__.py                  # public exports (imports MySensor)
│   ├── core.py                      # starter class with patterns
│   └── testing.py                   # test fakes (keep or delete)
├── tests/
│   ├── conftest.py                  # collection anchor (see note below)
│   └── test_my_sensor.py            # starter tests (100% coverage)
├── docs/
│   ├── index.md                     # docs landing page
│   ├── guide.md                     # user guide (rewrite the worked example)
│   ├── api.md                       # API reference (mkdocstrings renders it)
│   └── testing.md                   # testing helpers docs
├── examples/
│   ├── basic_usage.py               # MySensor in a while True: loop
│   └── helpers.py                   # wifi-up helper (delete if unused)
└── functional_tests/
    └── .gitkeep                     # on-device tests live here
```

`sync-ide` updates `.idea/chumicro.iml`, `.idea/runConfigurations/`, `pyrightconfig.json`, `.vscode/tasks.json`, and `.vscode/settings.json`, so the editor picks up the new package at once. Git tracks all five, so they show in `git status` beside the new library.

The scaffold runs as created: tests pass at 100% coverage, lint is clean, and the example runs until you press Ctrl-C. Start by replacing the starter `MySensor` class in `core.py` with your real implementation.

Keep `tests/conftest.py`, empty as it looks. The workspace runs one pytest rootdir over every library with `--import-mode=importlib`, and the file makes each `tests/` folder its own collection root, so same-named test modules in sibling libraries stay apart.

## 2. Implement

Your code goes in `src/chumicro_my_sensor/` and follows the [Style Guide](style-guide.md). Library code also follows these rules:

- **A service implements `check(now_ms)` and `handle(now_ms)`**, with no `async` or `await`, so [`Runner`](https://chumicro.com/ChuMicro/runner/stable/) can drive it ([Style Guide § Cooperative concurrency](style-guide.md#cooperative-concurrency)).
- **Every dependency runs on all three runtimes.**
- **Annotations use built-in syntax**, `int | None` and `list[int]`, with no `typing` import ([Style Guide § Type annotations](style-guide.md#type-annotations)).
- **Memory patterns wait for a measurement** ([Style Guide § Memory patterns](style-guide.md#memory-patterns-library-code-only)).

### Constructor injection

Pass time sources, I/O objects, and network sockets in as constructor parameters, and keep hardware modules out of the top-level imports:

```python
# ✅ Good: testable, injectable
class MySensor:
    """Reads from a sensor on a schedule."""

    def __init__(self, i2c: object, interval_ms: int = 1000) -> None:
        self._i2c = i2c
        self._interval_ms = interval_ms
```

```python
# ❌ Bad: hard-wired to hardware, can't test without a board
import board
import busio

class MySensor:
    def __init__(self) -> None:
        self._i2c = busio.I2C(board.SCL, board.SDA)
```

[Decision 0010](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0010-library-testability.md) records the reasoning.

### Public API

Export the public API from `__init__.py`:

```python
"""ChuMicro my_sensor: one-line description."""

from chumicro_my_sensor.core import MySensor

__all__ = ["MySensor"]
```

## 3. Write tests

Tests go in `libraries/my_sensor/tests/`, and the library meets the coverage gate in its own test run ([Style Guide § Coverage exclusions](style-guide.md#coverage-exclusions)).

```bash
pytest libraries/my_sensor/tests/                           # everyday iteration
pytest libraries/my_sensor/tests/test_my_sensor.py -x -v    # one file, stop on first failure
python scripts/run.py test --libraries my_sensor            # gated run with coverage enforcement
```

### What a test looks like

A test passes a fake in through the constructor:

```python
"""Tests for MySensor reading behavior."""

from chumicro_my_sensor import MySensor


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

A test file runs on CPython and on both unix ports, so it uses plain `assert`, lightweight fakes for your own interfaces, and fakes from other ChuMicro libraries, such as `from chumicro_timing.testing import FakeTicks`. Exception checks take `raises` from `chumicro_test_harness`. `pytest` and `unittest.mock` stay out of these files.

### Testing submodule

Keep `src/chumicro_my_sensor/testing.py` when downstream libraries or users would benefit from your fakes, and fill it with real ones. With nothing worth faking, delete it and its references:

1. Delete `src/chumicro_my_sensor/testing.py`
2. Delete `docs/testing.md`
3. Remove `- Testing Helpers: testing.md` from `mkdocs.yml`
4. Remove the Testing Helpers bullet from `docs/index.md`
5. Remove the `### Testing` group from the README's "What's included" section

### Functional tests on real boards

The scaffold also creates `functional_tests/` for behavior that needs a real board. It can stay empty at first. A library with timing-, transport-, GPIO-, or storage-sensitive behavior gains real-board tests there once the unit tests are stable.

Run them with:

```bash
python scripts/run.py test-libraries-functional --library my_sensor
```

[Device Testing](device-testing.md) covers `devices.yml`, deploy modes, and IDE play-button behavior.

## 4. Write docs

### User guide (`docs/guide.md`)

The scaffolded guide is a worked example for a fictional countdown timer. Rewrite each section for your library in the same order, and drop the Runner pattern and Memory notes sections when they don't apply. An AI agent writes it through the [`guide-generation` skill](https://github.com/ChuMicro/ChuMicro/tree/main/.github/skills/guide-generation/SKILL.md).

```bash
python scripts/run.py docs --libraries my_sensor
```

### API reference (`docs/api.md`)

mkdocstrings renders the API reference from your docstrings. The scaffold starts with a single directive. Add section headings and per-module directives as you add modules, as `libraries/timing/docs/api.md` does.

Every public function, method, and class needs a docstring, in the format [Style Guide § Docstrings](style-guide.md#docstrings) sets.

## 5. Write examples

Examples go in `libraries/my_sensor/examples/` and follow [Style Guide § Examples and demos](style-guide.md#examples-and-demos). Check them with:

```bash
python scripts/run.py verify-examples --libraries my_sensor
```

## 6. Fill in metadata

In `libraries/my_sensor/pyproject.toml`, set:

- `description`: one line, shown on the docs landing page
- `dependencies`: the other ChuMicro libraries yours depends on, such as `"chumicro-timing>=0.1"`

Rewrite `libraries/my_sensor/README.md` from its worked example, the same fictional countdown timer, for your library. Keep its section names, and leave the Contributing section as it renders.

## 7. Preflight and PR

```bash
python scripts/run.py preflight
```

Open the pull request as [Creating a Pull Request](pull-requests.md) describes. A new package's first release needs a PyPI pending publisher registered before the merge, which a maintainer sets up as [First release of a new package](releases.md#first-release-of-a-new-package) describes.

## 8. After merge

The merge publishes the library's first experimental release, as [What happens on merge](releases.md#what-happens-on-merge) describes, and users can [install it from experimental](releases.md#installing-from-experimental) at once. A [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) asks a maintainer to promote it to stable.

## Checklist

- [ ] `python scripts/run.py new-library <name>`: scaffold created
- [ ] Implementation in `src/chumicro_<name>/`
- [ ] Public exports in `__init__.py` with `__all__`
- [ ] Tests in `tests/`: coverage gate passing
- [ ] Testing submodule: kept and implemented, or deleted with all references
- [ ] Examples in `examples/`: `verify-examples` passes
- [ ] `docs/guide.md`: rewritten for your library
- [ ] `README.md`: rewritten for your library
- [ ] `pyproject.toml`: description and dependencies set
- [ ] Preflight passes
- [ ] PR opened and CI green
