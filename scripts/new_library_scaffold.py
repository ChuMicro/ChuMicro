"""Library scaffolding — templates and directory creation.

Creates the full directory layout, configuration files, docs skeleton,
and starter source for a new chumicro library.  Called via::

    python scripts/run.py new-library <name>

After scaffolding, IDE configurations are regenerated automatically so
the new library's ``src/`` is immediately importable without any manual
setup.  See ``plans/decisions/0013-docs-and-examples-standards.md`` for
the documentation structure conventions.

**Template synchronization:** Templates live in ``scripts/templates/``
as ``.template`` files.  When a template changes (e.g., new mkdocs
settings, new README section, new pyproject fields), apply the same
structural change to all existing libraries.  Template updates do not
propagate retroactively.
"""

from __future__ import annotations

from ide_sync import sync_ide
from shared import install_editable, load_template
from workspace import ROOT


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
        load_template("pyproject.toml.template").format(
            name=name, import_name=import_name,
        )
    )

    # mkdocs.yml
    (library_dir / "mkdocs.yml").write_text(
        load_template("mkdocs.yml.template").format(name=name)
    )

    # README
    (library_dir / "README.md").write_text(
        load_template("readme.md.template").format(
            name=name, import_name=import_name,
        )
    )

    # docs/
    (library_dir / "docs" / "index.md").write_text(
        load_template("index.md.template").format(
            name=name, import_name=import_name,
        )
    )

    # docs/guide.md
    (library_dir / "docs" / "guide.md").write_text(
        load_template("guide.md.template").format(name=name)
    )

    # docs/api.md
    (library_dir / "docs" / "api.md").write_text(
        load_template("api.md.template").format(
            name=name, import_name=import_name,
        )
    )

    # docs/testing.md
    (library_dir / "docs" / "testing.md").write_text(
        load_template("testing.md.template").format(
            name=name, import_name=import_name,
        )
    )

    # Example
    display_name = name.replace("-", " ").replace("_", " ").title()
    (library_dir / "examples" / "quickstart.py").write_text(
        load_template("quickstart.py.template").format(
            name=name,
            display_name=display_name,
            import_name=import_name,
            class_name=class_name,
        )
    )

    # Package __init__.py — exports the starter class.
    #
    # Uses an absolute import (`from chumicro_<name>.core import ...`)
    # because libraries/*/src/ is in scope of ruff TID252 (Decision 0035 / 0036
    # context — CircuitPython RAM-mode `exec()`s library modules without a
    # `__package__`, so relative imports break at deploy).  See AGENTS.md
    # non-negotiables.
    #
    # Loading-shape note:  this scaffold uses eager imports (Tier A per
    # `plans/workstreams/lazy-loading-research.md` — fine for small-surface
    # libraries with no per-runtime adapters).  If this library grows past
    # ~5 public attributes spread across submodules OR adds per-runtime
    # adapters under `_backends/` / `_adapters/`, switch to the PEP 562
    # `__getattr__` table pattern (see `plans/patterns.md` "Lazy module-
    # level imports via PEP 562").
    (library_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
        f"\n"
        f"from {import_name}.core import {class_name}\n"
        f"\n"
        f'__all__ = ["{class_name}"]\n'
    )

    # core.py — starter implementation with project patterns
    (library_dir / "src" / import_name / "core.py").write_text(
        load_template("core.py.template").format(
            name=name, class_name=class_name,
        )
    )

    # testing.py stub — delete if the library has no injectable services
    (library_dir / "src" / import_name / "testing.py").write_text(
        load_template("testing.py.template").format(
            name=name, import_name=import_name,
        )
    )

    # Tests conftest.py (no __init__.py — avoids module name collisions across libraries)
    (library_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the chumicro-{name} package."""\n'
    )

    # Starter test file demonstrating test patterns
    test_name = name.replace("-", "_")
    (library_dir / "tests" / f"test_{test_name}.py").write_text(
        load_template("test_library.py.template").format(
            import_name=import_name, class_name=class_name,
        )
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
