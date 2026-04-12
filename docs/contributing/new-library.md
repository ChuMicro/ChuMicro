# Adding a New Library

This guide walks you through the full lifecycle of adding a new library to ChuMicro — from idea to published package. If you're working with an AI agent, point it at the [`new-library` skill](../../.github/skills/new-library/SKILL.md).

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
└── functional_tests/                # on-device tests
```

The scaffold is immediately runnable — tests pass at 100% coverage, lint is clean, and the example executes. Start by replacing the starter `MyThing` class in `core.py` with your real implementation.

## 2. Implement

Put your code in `src/chumicro_my_thing/`. Follow the [Style Guide](style-guide.md) for naming, annotations, docstrings, and formatting. Key rules for library code:

- **No `async`/`await`** — use the tick-based runner pattern. If your library has active components, implement `check(now_ms) -> bool` so they work with [`Runner`](../../libraries/runner/).
- **No third-party dependencies** that aren't available on all three runtimes.
- **No `typing` imports** — use PEP 604/585 syntax: `int | None`, `list[int]`.
- **Constructor injection** — accept dependencies (time, I/O, network) as constructor parameters. Don't import hardware modules at the top level. See [Decision 0010](../../plans/decisions/0010-library-testability.md).
- **Memory patterns are optional on day one** — `const()`, `memoryview`, pre-allocated buffers. Focus on correctness first. The [Style Guide](style-guide.md#memory-patterns-library-code-only) has the full list when you're ready.

Export your public API from `__init__.py`:

```python
"""ChuMicro my-thing — one-line description."""

from chumicro_my_thing.core import MyClass, helper_function

__all__ = ["MyClass", "helper_function"]
```

## 3. Write tests

Tests go in `libraries/my-thing/tests/`. The coverage threshold is **94%** — every library must meet it independently.

```bash
python scripts/run.py test --libraries my-thing

# Quick iteration (skip coverage, stop on first failure)
python scripts/run.py test -k my-thing/test_core -x -v --no-cov
```

Create lightweight fakes for your own interfaces and inject them via constructors. Use fakes from upstream ChuMicro libraries (`from chumicro_timing.testing import FakeTicks`). Don't use `unittest.mock` on third-party APIs.

### Testing submodule

If downstream libraries or users would benefit from test fakes, keep `src/chumicro_my_thing/testing.py` and implement real fakes. If there's nothing worth faking, delete it and its references:

1. Delete `src/chumicro_my_thing/testing.py`
2. Delete `docs/testing.md`
3. Remove `- Testing Helpers: testing.md` from `mkdocs.yml`
4. Remove the Testing Helpers link from `docs/index.md` and `README.md`

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

## 7. Preflight and PR

```bash
python scripts/run.py preflight
```

Must print `Preflight passed`. Then push and open a PR on GitHub targeting `main`. See [Creating a Pull Request](pull-requests.md) for the full walkthrough.

When your PR merges, the VERSION bump triggers an automatic experimental release. See [Releases](releases.md) for the full release model, including how to request stable promotion.

## Checklist

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
