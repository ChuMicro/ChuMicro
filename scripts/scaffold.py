"""Library scaffolding — templates and directory creation.

Creates the full directory layout, configuration files, docs skeleton,
and starter source for a new chumicro library.  Called via::

    python scripts/run.py new-library <name>

After scaffolding, IDE configurations are regenerated automatically so
the new library's ``src/`` is immediately importable without any manual
setup.  See ``plans/decisions/0013-docs-and-examples-standards.md`` for
the documentation structure conventions.

**Template synchronization:** These templates produce a point-in-time
starting state.  When a template changes (e.g., new mkdocs settings,
new README section, new pyproject fields), apply the same structural
change to all existing libraries.  Template updates do not propagate
retroactively.
"""

from __future__ import annotations

from discovery import ROOT
from ide import sync_ide
from workspace import install_editable

# ---------------------------------------------------------------------------
# Template strings
# ---------------------------------------------------------------------------
# Each constant below is a format-string template written to the new
# library's directory tree.  Placeholders:
#   {name}        — the library short name (e.g. "gpio")
#   {import_name} — the Python package name (e.g. "chumicro_gpio")

#: Hatchling-based build configuration.  ``dynamic = ["version"]`` reads
#: the version from the ``VERSION`` file at build time.
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

#: MkDocs Material configuration for the library's documentation site.
_MKDOCS_TEMPLATE = """\
site_name: chumicro-{name}
site_url: https://chumicro.github.io/ChuMicro/{name}/
repo_url: https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name}
repo_name: Source
theme:
  name: material
  palette:
    scheme: slate
    primary: deep purple
    accent: purple
  font:
    text: Inter
    code: JetBrains Mono
  icon:
    repo: fontawesome/brands/github
  favicon: img/favicon.png

extra_css:
  - stylesheets/extra.css

extra:
  version:
    provider: mike
    default:
      - stable
      - experimental
  homepage: ../../

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
            docstring_style: google
            docstring_options:
              returns_named_value: false
            show_source: false
            show_root_heading: true
            members_order: source
"""

#: Landing page for the library's docs site.
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

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
· [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
"""

#: Top-level README shown on GitHub and PyPI.
_README_TEMPLATE = """\
# chumicro-{name}

<!-- TODO: Add a one-line description of what the library does. -->

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

[circup](https://github.com/adafruit/circup) is CircuitPython's package manager — \
it uses bundles to find third-party packages. Register the ChuMicro bundle once, \
then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-{name}
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/{import_name}
```

### CPython (pip)

```bash
pip install chumicro-{name}
```

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. \
Do not register both bundles simultaneously — circup may pick either version \
for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-{name}

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/{import_name}

# CPython
pip install chumicro-{name}-experimental
```

</details>

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

#: User guide skeleton with required section headings.
_GUIDE_TEMPLATE = """\
# User Guide

<!-- GENERATION INSTRUCTIONS — delete this block once the guide is written.

     This guide should be generated from the library's source code, docstrings,
     tests, and examples.  See the guide-generation skill for the
     full prompt an AI agent can use.  Every section below is required unless
     marked conditional.  Do not leave placeholder comments in the final guide. -->

## Overview

<!-- Required. 2-4 sentences: what the library does, why it exists, the core
     concept. Name the key classes/functions. -->

## Getting started

<!-- Required. The most common usage pattern as a copy-pasteable snippet.
     Import from the public package, not internal modules. -->

## Runner pattern

<!-- Conditional. Include if the library has classes that implement
     check(now_ms) -> bool. Show how to wire them into a Runner.
     Omit if not applicable. -->

## Memory notes

<!-- Conditional. Include if the library manages buffers, queues, or
     pre-allocated structures. Explain allocation strategy and tuning. -->

## Platform notes

<!-- Required. Runtime-specific behavior or limitations. If the library works
     identically on all three runtimes, say so in one line. -->

## Examples

<!-- Required. List all examples from the examples/ directory in a table:
     | Example | What it shows |
     Note which are simulated (CPython) vs hardware. -->

## What's new

<!-- Add entries for user-visible changes when bumping VERSION.
     One bullet per change. Internal refactors don't need entries.
     At stable promotion, collapse/edit as needed. -->

*No changes yet — this section will be updated with each release.*

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
· [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
"""

#: Documentation page for the library's ``testing`` submodule fakes.
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

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
· [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
"""

#: Starter ``testing.py`` module with instructions for creating fakes.
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

#: API reference page — delegates to mkdocstrings autodoc.
_API_TEMPLATE = """\
# API Reference

::: {import_name}

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
· [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
"""

#: Minimal example script included as ``examples/quickstart.py``.
_EXAMPLE_TEMPLATE = """\
\"\"\"{display_name} quickstart.

Shows basic usage of the {display_name} class.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    Created {display_name} with value=42
    Current value: 42
    Value after update: 100
\"\"\"

from {import_name} import {class_name}

thing = {class_name}(value=42)
print(f"Created {display_name} with value={{thing.value}}")

print(f"Current value: {{thing.value}}")

thing.update(100)
print(f"Value after update: {{thing.value}}")
"""

#: Starter implementation module demonstrating project patterns.
_CORE_TEMPLATE = """\
\"\"\"Core implementation for chumicro-{name}.\"\"\"


class {class_name}:
    \"\"\"A starter class demonstrating Chumicro library patterns.

    Replace this with your real implementation.  This placeholder shows:

    - Constructor injection (Decision 0010)
    - Type annotations with description-only docstrings (Decision 0021)
    - A ``check(now_ms)`` method for Runner integration (Decision 0014)

    Args:
        value: Initial value.
    \"\"\"

    def __init__(self, value: int = 0) -> None:
        \"\"\"Create a new {class_name}.

        Args:
            value: Initial value.
        \"\"\"
        self._value = value

    @property
    def value(self) -> int:
        \"\"\"Return the current value.

        Returns:
            The current value.
        \"\"\"
        return self._value

    def update(self, new_value: int) -> None:
        \"\"\"Update the stored value.

        Args:
            new_value: The new value to store.
        \"\"\"
        self._value = new_value

    def check(self, now_ms: int) -> bool:
        \"\"\"Tick-based check for Runner integration.

        Called once per tick by the Runner.  Replace this with real
        logic or remove if the library has no active components.

        Args:
            now_ms: Current tick value in milliseconds.

        Returns:
            ``True`` if something happened this tick.
        \"\"\"
        return False
"""

#: Starter test file demonstrating testing patterns.
_TEST_TEMPLATE = """\
\"\"\"Tests for {import_name}.\"\"\"

import {import_name}


class Test{class_name}:
    \"\"\"Tests for the {class_name} class.\"\"\"

    def test_default_value(self):
        \"\"\"Default value is zero.\"\"\"
        thing = {import_name}.{class_name}()
        assert thing.value == 0

    def test_initial_value(self):
        \"\"\"{class_name} stores the initial value.\"\"\"
        thing = {import_name}.{class_name}(value=42)
        assert thing.value == 42

    def test_update(self):
        \"\"\"update() changes the stored value.\"\"\"
        thing = {import_name}.{class_name}(value=1)
        thing.update(99)
        assert thing.value == 99

    def test_check_returns_false(self):
        \"\"\"Placeholder check always returns False.\"\"\"
        thing = {import_name}.{class_name}()
        assert thing.check(now_ms=0) is False
"""


def _scaffold_library(name: str) -> int:
    """Create the directory structure and template files for a new library.

    Args:
        name: Library short name (e.g. ``"gpio"``).

    The resulting layout matches the workspace convention::

        libraries/<name>/
        ├── VERSION                       # semver, starts at 0.1.0
        ├── pyproject.toml                # Hatchling build config
        ├── mkdocs.yml                    # docs site config
        ├── README.md                     # GitHub/PyPI readme
        ├── src/chumicro_<name>/
        │   ├── __init__.py               # public exports
        │   ├── core.py                   # starter implementation
        │   └── testing.py                # test fakes stub
        ├── tests/
        │   ├── conftest.py               # per-library pytest config
        │   └── test_<name>.py            # starter tests
        ├── functional_tests/             # on-device tests (empty)
        ├── docs/                         # MkDocs source pages
        │   ├── index.md, guide.md, api.md, testing.md
        └── examples/
            └── quickstart.py             # starter example
    """
    import_name = f"chumicro_{name.replace('-', '_')}"
    # Class name: "my-thing" → "MyThing"
    class_name = "".join(
        part.capitalize() for part in name.replace("-", "_").split("_")
    )

    library_dir = ROOT / "libraries" / name

    if library_dir.exists():
        print(f"Directory already exists: libraries/{name}")
        return 1

    # Create directory tree
    (library_dir / "src" / import_name).mkdir(parents=True)
    (library_dir / "tests").mkdir()
    (library_dir / "functional_tests").mkdir()
    (library_dir / "docs").mkdir()
    (library_dir / "examples").mkdir()

    # .gitkeep for directories that start empty
    (library_dir / "functional_tests" / ".gitkeep").touch()

    # VERSION
    (library_dir / "VERSION").write_text("0.1.0\n")

    # pyproject.toml
    (library_dir / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(name=name, import_name=import_name)
    )

    # mkdocs.yml
    (library_dir / "mkdocs.yml").write_text(_MKDOCS_TEMPLATE.format(name=name))

    # README
    (library_dir / "README.md").write_text(
        _README_TEMPLATE.format(name=name, import_name=import_name)
    )

    # docs/
    (library_dir / "docs" / "index.md").write_text(
        _INDEX_TEMPLATE.format(name=name, import_name=import_name)
    )

    # docs/guide.md
    (library_dir / "docs" / "guide.md").write_text(
        _GUIDE_TEMPLATE.format(name=name)
    )

    # docs/api.md
    (library_dir / "docs" / "api.md").write_text(
        _API_TEMPLATE.format(name=name, import_name=import_name)
    )

    # docs/testing.md
    (library_dir / "docs" / "testing.md").write_text(
        _TESTING_DOC_TEMPLATE.format(name=name, import_name=import_name)
    )

    # Example
    display_name = name.replace("-", " ").replace("_", " ").title()
    (library_dir / "examples" / "quickstart.py").write_text(
        _EXAMPLE_TEMPLATE.format(
            name=name,
            display_name=display_name,
            import_name=import_name,
            class_name=class_name,
        )
    )

    # Package __init__.py — exports the starter class
    (library_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
        f"\n"
        f"from .core import {class_name}\n"
        f"\n"
        f'__all__ = ["{class_name}"]\n'
    )

    # core.py — starter implementation with project patterns
    (library_dir / "src" / import_name / "core.py").write_text(
        _CORE_TEMPLATE.format(name=name, class_name=class_name)
    )

    # testing.py stub — delete if the library has no injectable services
    (library_dir / "src" / import_name / "testing.py").write_text(
        _TESTING_PY_TEMPLATE.format(name=name, import_name=import_name)
    )

    # Tests conftest.py (no __init__.py — avoids module name collisions across libraries)
    (library_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the chumicro-{name} package."""\n'
    )

    # Starter test file demonstrating test patterns
    test_name = name.replace("-", "_")
    (library_dir / "tests" / f"test_{test_name}.py").write_text(
        _TEST_TEMPLATE.format(import_name=import_name, class_name=class_name)
    )

    print(f"Created libraries/{name}/")
    return 0


def new_library(name: str) -> int:
    """Scaffold a new library under libraries/ and regenerate IDE configurations.

    Args:
        name: Library short name (e.g. ``"gpio"``).
    """
    result = _scaffold_library(name)
    if result != 0:
        return result

    result = install_editable()
    if result != 0:
        return result

    return sync_ide()
