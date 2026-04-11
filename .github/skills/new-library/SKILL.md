---
name: new-library
description: Full lifecycle for creating a new ChuMicro library — from scaffolding through release-ready. Use this skill when adding a new library to the workspace.
---

# New Library Lifecycle

This skill covers the full workflow from scaffolding a new library through making it release-ready. The scaffold command creates the skeleton; everything after that is on you.

## 1. Scaffold

```bash
python scripts/run.py new-library <name>
```

This creates `libraries/<name>/` with the full directory tree (including a starter class in `core.py`, a passing test file, and a working example), regenerates IDE configs, and prints what was created. The scaffold is immediately runnable — tests pass at 100% coverage, lint is clean, and the example executes. Verify:

```bash
python scripts/run.py test --libraries <name> 2>&1 | tail -5
```

## 2. Write the implementation

The scaffold creates a starter class in `src/chumicro_<name>/core.py` that demonstrates constructor injection, Google-style docstrings, and a `check(now_ms)` method. Replace it with your real code.

Put production code in `src/chumicro_<name>/`.

**Rules for library code** (these run on microcontrollers):

- No `async`/`await` — use the tick-based runner pattern (Decision 0014).
- Constructor injection for time, I/O, network (Decision 0010).
- Docstring descriptions only; type annotations on signatures (Decision 0021).
- f-strings for formatting. `const()` / `memoryview` / pre-allocated buffers where appropriate.
- Minimize dependencies — prefer pure-Python compatible with all three runtimes.
- If the library has active components, implement `check(now_ms) -> bool` so they work with `Runner`.

**Public API goes in `__init__.py`:**

```python
"""Public exports for the chumicro-<name> package."""

from chumicro_<name>.core import MyClass, my_function

__all__ = ["MyClass", "my_function"]
```

## 3. Write tests

Tests go in `libraries/<name>/tests/`. Run with:

```bash
python scripts/run.py test --libraries <name>
```

**Requirements:**

- 94% branch coverage gate. Check with: `python scripts/run.py test --libraries <name> 2>&1 | tail -20`
- Use constructor injection — accept dependencies as parameters, don't import globals.
- Per-library pytest runs (Decision 0009) — never bare `pytest` from root.
- Use fakes from upstream libraries (`from chumicro_timing.testing import FakeTicks`), don't mock what you don't own (Decision 0010).

**Quick iteration:**

```bash
python scripts/run.py test -k <name>/test_something -x -v --no-cov
```

## 4. Add a testing submodule (if applicable)

If the library exposes injectable services that downstream consumers need to fake, create `src/chumicro_<name>/testing.py` with ready-made fakes.

The scaffold creates a stub `testing.py` with instructions. **If the library has nothing worth faking, delete it** and remove all testing-helper references:

1. Delete `src/chumicro_<name>/testing.py`
2. Delete `docs/testing.md`
3. Remove `- Testing Helpers: testing.md` from `mkdocs.yml`
4. Remove the Testing Helpers link from `docs/index.md`
5. Remove the Testing helpers link from `README.md`

## 5. Write examples

Put examples in `libraries/<name>/examples/`. At least one per major feature.

**Rules (Decision 0013):**

- Top-level code — no `if __name__ == "__main__":` guard.
- Simulated examples must run on CPython without hardware.
- Hardware examples: name `circuitpython_*.py` or `micropython_*.py`.
- Descriptive filenames: `heartbeat_blink.py`, not `example1.py`.
- Module docstring with `Example output::` block.
- Self-contained: copy-paste and run.

Verify examples pass:

```bash
python scripts/run.py verify-examples --libraries <name>
```

## 6. Write the user guide

Use the `guide-generation` skill to generate `docs/guide.md`. The scaffold creates a placeholder — replace it with real content derived from the source code.

Verify docs build:

```bash
python scripts/run.py docs --libraries <name>
```

Preview locally:

```bash
python scripts/run.py docs --libraries <name> --serve
```

## 7. Fill in the README

The scaffold generates `README.md` with TODO placeholders. Fill in:

- One-line description
- API summary table (what's included)
- Platform support notes

## 8. Update pyproject.toml

The scaffold generates a minimal `pyproject.toml`. Update:

- `description` — one-line package description
- `dependencies` — if the library depends on other chumicro libraries (e.g., `"chumicro-timing>=0.1"`)
- `[tool.chumicro].platforms` — only if the library doesn't target all three runtimes (omit for all-platform)

## 9. Bump VERSION if needed

VERSION starts at `0.1.0`. Leave it unless you're making a second release. For subsequent changes:

- Patch (`0.1.1`): bug fixes, internal changes
- Minor (`0.2.0`): new features, breaking changes while pre-1.0
- Major (`1.0.0`): stable API declaration

## 10. Run preflight

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

Must show: `Preflight passed — required CI checks should pass.`

This runs: lint, build, docs (with griffe warning detection), tests (94% coverage), verify-examples, check-version, check-api, and cross-runtime compatibility.

## 11. Commit

Use the `git-commit` skill. Write a message naming the new library and summarizing what it provides.

## Checklist

```
[ ] Scaffold: python scripts/run.py new-library <name>
[ ] Implementation in src/chumicro_<name>/
[ ] Public exports in __init__.py
[ ] Tests in tests/ — 94% coverage
[ ] Testing submodule decision: keep and implement, or delete with all references
[ ] Examples in examples/ — verify-examples passes
[ ] docs/guide.md — real content, no placeholders
[ ] README.md — description and API summary filled in
[ ] pyproject.toml — description and dependencies
[ ] Preflight passes
[ ] Committed with clean tree
```

