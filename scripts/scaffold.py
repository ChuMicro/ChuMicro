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
Source = "https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/{name}"
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
repo_url: https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/{name}
repo_name: Source
theme:
  name: material
  palette:
    scheme: slate
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

## Links

[**← All ChuMicro Libraries**](https://chumicro.github.io/ChuMicro/){{ .md-button }}

[Source on GitHub](https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/{name})
· [PyPI](https://pypi.org/project/chumicro-{name}/)
· [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle)
"""

_README_TEMPLATE = """\
# chumicro-{name}

## Installation

```bash
pip install chumicro-{name}
```

## Quick example

```python
from {import_name} import ...
```

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/{name}/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/{name}/experimental/)**

Browse on GitHub:

- [User guide](docs/guide.md)
- [API reference](docs/api.md)
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

    # Example
    display_name = name.replace("-", " ").replace("_", " ").title()
    (lib_dir / "examples" / "quickstart.py").write_text(
        _EXAMPLE_TEMPLATE.format(name=name, display_name=display_name)
    )

    # Package __init__.py
    (lib_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
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

