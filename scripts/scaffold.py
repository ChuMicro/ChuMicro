"""Library scaffolding — templates and directory creation."""

from __future__ import annotations

from discovery import ROOT
from ide import sync_ide

_PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "chumicro-{name}"
dynamic = ["version"]
description = ""
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [
    {{ name = "Chumicro" }},
]
keywords = [
    "circuitpython", "micropython", "microcontroller", "embedded",
    "esp32", "rp2040",
]
classifiers = [
    "Development Status :: 2 - Pre-Alpha",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Topic :: Software Development :: Embedded Systems",
    "Topic :: System :: Hardware",
    "Operating System :: OS Independent",
]

[project.urls]
Homepage = "https://github.com/ChuMicro/ChuMicro"
Documentation = "https://chumicro.github.io/ChuMicro/{name}/stable/"
Source = "https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name}"
Issues = "https://github.com/ChuMicro/ChuMicro/issues"
Bundle = "https://github.com/ChuMicro/ChuMicro-Bundle"

[tool.hatch.version]
path = "VERSION"
pattern = "(?P<version>\\\\S+)"

[tool.hatch.build.targets.sdist]
include = ["src/", "VERSION", "README.md"]
exclude = [".gitignore"]

[tool.hatch.build.targets.wheel]
packages = ["src/{import_name}"]
"""

_MKDOCS_TEMPLATE = """\
site_name: chumicro-{name}
site_url: https://chumicro.github.io/ChuMicro/{name}/
repo_url: https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name}
repo_name: Source
theme:
  name: material
  palette:
    scheme: default
    primary: deep purple
    accent: purple
  icon:
    repo: fontawesome/brands/github

extra:
  version:
    provider: mike
    default:
      - stable
      - experimental
  homepage: https://chumicro.github.io/ChuMicro/


nav:
  - Home: index.md
  - Guide: guide.md
  - API Reference: api.md
  - Testing Helpers: testing.md

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths:
            - src
          options:
            show_source: false
            show_root_heading: true
            members_order: source
"""

_INDEX_TEMPLATE = """\
# chumicro-{name}

<!-- Replace this with a one-line description of the library. -->

## Quick example

```python
from {import_name} import ...
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
<!-- If this library has a testing submodule, uncomment the next line: -->
<!-- - [Testing Helpers](testing.md) — fakes for downstream test suites -->

---

[← All ChuMicro Libraries](https://chumicro.github.io/ChuMicro/)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
· [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
"""

_README_TEMPLATE = """\
# chumicro-{name}

<!-- TODO: Add a one-line description of what the library does. -->

## Installation

### CircuitPython (circup)

Register the ChuMicro bundle (remove the other channel first if switching):

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle-Experimental   # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-{name}
```

### MicroPython (mip)

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/{import_name}
```

### CPython (pip)

```bash
pip install chumicro-{name}
```

### Experimental (pre-release) versions

Pre-release builds are published automatically when a library version is bumped.\
  Do not register both bundles simultaneously — circup may pick either version\
 for a given package.

```bash
# CircuitPython
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-{name}

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/{import_name}

# CPython
pip install chumicro-{name}-experimental
```

## Quick example

```python
from {import_name} import ...
```

## What's included

<!-- TODO: Add API summary tables (see other library READMEs for format). -->

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

<!-- TODO: Add an examples table once examples are written.
| Example | What it shows |
|---|---|
| `example.py` | Description |
-->

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/{name}/stable/)** · \
**[Experimental docs](https://chumicro.github.io/ChuMicro/{name}/experimental/)**

Browse on GitHub:

- [User guide](docs/guide.md)
- [API reference](docs/api.md)
<!-- If this library has a testing submodule, uncomment the next line: -->
<!-- - [Testing helpers](docs/testing.md) -->

## Find this library

**PyPI:** [chumicro-{name}](https://pypi.org/project/chumicro-{name}/)
**Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)\
 (CircuitPython & MicroPython)
**Source:** [ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro) —\
 cross-runtime Python libraries for ESP32, RP2040, and other microcontrollers.
"""

_GUIDE_TEMPLATE = """\
# User Guide

<!-- GENERATION INSTRUCTIONS — delete this block once the guide is written.

     This guide should be generated from the library's source code, docstrings,
     tests, and examples.  See plans/prompts/guide-generation.prompt.md for the
     full prompt an AI agent can use.  Every section below is required unless
     marked optional.  Do not leave placeholder comments in the final guide. -->

## Overview

<!-- Required. 2-4 sentences: what the library does, why it exists, the core
     concept. Name the key classes/functions. -->

## Getting started

<!-- Required. The most common usage pattern as a copy-pasteable snippet.
     Import from the public package, not internal modules. -->

## Platform notes

<!-- Required. Runtime-specific behavior or limitations. If the library works
     identically on all three runtimes, say so in one line. -->

## Runner pattern

<!-- Include if the library has classes that implement check(now_ms) -> bool.
     Show how to wire them into a Runner. Omit if not applicable. -->

## Memory notes

<!-- Optional. Include if the library manages buffers, queues, or
     pre-allocated structures. Explain allocation strategy and tuning. -->
"""

_TESTING_DOC_TEMPLATE = """\
# Testing Helpers

<!-- GENERATION INSTRUCTIONS — delete this block once the page is written.

     This page documents the fakes in the library's `testing` submodule.
     If this library does NOT expose injectable services that downstream
     consumers need to fake, delete all testing-helper references:
       1. Delete this file (`docs/testing.md`)
       2. Delete `src/{import_name}/testing.py`
       3. Remove the `- Testing Helpers: testing.md` line from `mkdocs.yml` nav
       4. Remove the Testing Helpers link from `docs/index.md`
       5. Remove the Testing helpers link from `README.md`

     Libraries that accept dependencies via constructor injection (time,
     I/O, network) should provide ready-made fakes so downstream tests
     don't have to invent their own mocks (Decision 0010).

     To fill this in, read:
       1. `src/{import_name}/testing.py` — the fake classes/functions
       2. `tests/` — see how the fakes are used in this library's own tests
       3. Existing examples: libraries/timing/docs/testing.md,
          libraries/runner/docs/testing.md

     Structure:
       - Open with one sentence: what the module provides and why.
       - One section per fake class, showing a realistic test snippet.
       - A "Usage from other libraries" section with a cross-library import.
       - An "API Reference" section with a ::: autodoc directive. -->

`{import_name}.testing` provides ...

## Usage

<!-- Show a realistic test snippet using the fake.  Import from the public
     testing submodule.  Use descriptive variable names. -->

```python
from {import_name}.testing import Fake...

def test_example():
    ...
```

## Usage from other libraries

Libraries that depend on `chumicro-{name}` can import the fakes directly:

```python
from {import_name}.testing import Fake...
```

This follows [Decision 0010][d0010]: libraries that expose injectable
services ship their own test fakes.

[d0010]: https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0010-library-testability.md

## API Reference

::: {import_name}.testing
"""

_TESTING_PY_TEMPLATE = """\
\"\"\"Test helpers for libraries that depend on chumicro-{name}.

Delete this file if the library does not expose injectable services
that downstream consumers need to fake.  If you delete this file, also
remove all testing-helper references:

  1. Delete ``docs/testing.md``
  2. Remove the ``- Testing Helpers: testing.md`` line from ``mkdocs.yml`` nav
  3. Remove the Testing Helpers link from ``docs/index.md``
  4. Remove the Testing helpers link from ``README.md``

When keeping this file, replace this docstring and the placeholder
class below with real fakes.  A good fake:

- Mirrors the interface that production code injects (same method
  names, same call signature).
- Lets tests control behavior deterministically (e.g., ``advance()``
  for time, ``enqueue()`` for I/O buffers).
- Records calls so tests can assert what happened.

See ``libraries/timing/src/chumicro_timing/testing.py`` (FakeTicks)
and ``libraries/runner/src/chumicro_runner/testing.py`` (CallRecorder)
for real examples.

Usage from any library's tests::

    from {import_name}.testing import Fake...
\"\"\"
"""

_API_TEMPLATE = """\
# API Reference

::: {import_name}
"""

_EXAMPLE_TEMPLATE = """\
\"\"\"{display_name} example.

Describe what this example demonstrates.

Runs on CPython, MicroPython, and CircuitPython.
\"\"\"

print("Hello from chumicro-{name}!")
"""


def _scaffold_library(name: str) -> int:
    """Create the directory structure and template files for a new library."""
    import_name = f"chumicro_{name.replace('-', '_')}"
    lib_dir = ROOT / "libraries" / name

    if lib_dir.exists():
        print(f"Directory already exists: libraries/{name}")
        return 1

    # Create directory tree
    (lib_dir / "src" / import_name).mkdir(parents=True)
    (lib_dir / "tests").mkdir()
    (lib_dir / "functional_tests").mkdir()
    (lib_dir / "docs").mkdir()
    (lib_dir / "examples").mkdir()

    # .gitkeep for directories that start empty
    (lib_dir / "functional_tests" / ".gitkeep").touch()

    # VERSION
    (lib_dir / "VERSION").write_text("0.1.0\n")


    # pyproject.toml
    (lib_dir / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(name=name, import_name=import_name)
    )

    # mkdocs.yml
    (lib_dir / "mkdocs.yml").write_text(_MKDOCS_TEMPLATE.format(name=name))

    # README
    (lib_dir / "README.md").write_text(
        _README_TEMPLATE.format(name=name, import_name=import_name)
    )

    # docs/
    (lib_dir / "docs" / "index.md").write_text(
        _INDEX_TEMPLATE.format(name=name, import_name=import_name)
    )
    (lib_dir / "docs" / "guide.md").write_text(_GUIDE_TEMPLATE)


    (lib_dir / "docs" / "api.md").write_text(
        _API_TEMPLATE.format(import_name=import_name)
    )

    # docs/testing.md
    (lib_dir / "docs" / "testing.md").write_text(
        _TESTING_DOC_TEMPLATE.format(name=name, import_name=import_name)
    )

    # Example
    display_name = name.replace("-", " ").replace("_", " ").title()
    (lib_dir / "examples" / "quickstart.py").write_text(
        _EXAMPLE_TEMPLATE.format(name=name, display_name=display_name)
    )

    # Package __init__.py
    (lib_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
    )

    # testing.py stub — delete if the library has no injectable services
    (lib_dir / "src" / import_name / "testing.py").write_text(
        _TESTING_PY_TEMPLATE.format(name=name, import_name=import_name)
    )

    # Tests conftest.py (no __init__.py — avoids module name collisions across libraries)
    (lib_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the chumicro-{name} package."""\n'
    )

    print(f"Created libraries/{name}/")
    return 0


def new_library(name: str) -> int:
    """Scaffold a new library under libraries/ and regenerate IDE configs."""
    result = _scaffold_library(name)
    if result != 0:
        return result

    return sync_ide()

