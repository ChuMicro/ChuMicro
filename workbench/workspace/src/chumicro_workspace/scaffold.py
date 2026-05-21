"""Create chumicro-style library and workbench package trees.

The output layout::

    libraries/<name>/
    ├── VERSION
    ├── pyproject.toml
    ├── mkdocs.yml
    ├── README.md
    ├── src/chumicro_<name>/
    │   ├── __init__.py
    │   ├── core.py
    │   └── testing.py
    ├── tests/
    │   ├── conftest.py
    │   └── test_<name>.py
    ├── functional_tests/
    │   └── .gitkeep
    ├── docs/
    │   ├── index.md, guide.md, api.md, testing.md
    └── examples/
        └── basic_usage.py

Templates ship beside this module under ``_payloads/library_template/``
and travel with the wheel.  ``package_kind="workbench"`` swaps the
four ``docs/`` templates for a workbench-flavored set under
``_payloads/workbench_template/``; every other file is shared.

``python run.py new --library <name>`` is the usual entry point.
Callers that need finer control call :func:`scaffold_library`
directly with an explicit target directory.
"""

from __future__ import annotations

from pathlib import Path

#: Default template root.  Holds pyproject, README, mkdocs, src/,
#: tests/, examples/, and the library-flavored docs/ templates.
#: Every scaffold reads from here unless explicitly overridden.
_LIBRARY_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "_payloads" / "library_template"
)

#: Override root for workbench-kind packages.  Carries only the
#: four docs/ templates (index.md, guide.md, api.md, testing.md).
#: Every other file in a workbench scaffold still loads from
#: :data:`_LIBRARY_TEMPLATE_DIR`.
_WORKBENCH_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "_payloads" / "workbench_template"
)


class LibraryAlreadyExistsError(FileExistsError):
    """Raised when the scaffold target directory already exists.

    Carries the path so callers can construct a precise message
    without re-deriving it.
    """


def _load_template(
    filename: str, *, template_dir: Path = _LIBRARY_TEMPLATE_DIR,
) -> str:
    """Read a scaffolding template by filename.

    Defaults to :data:`_LIBRARY_TEMPLATE_DIR`.  Pass
    *template_dir=_WORKBENCH_TEMPLATE_DIR* for the workbench-flavored
    docs templates.  Pure filesystem read, no caching, no formatting.
    """
    template_path = template_dir / filename
    if not template_path.is_file():
        raise FileNotFoundError(
            f"library scaffold template missing at {template_path} — "
            "chumicro-workspace install may be broken; reinstall.",
        )
    return template_path.read_text()


def _import_name(name: str) -> str:
    """Map ``my-project`` → ``chumicro_my_project`` for source imports."""
    return f"chumicro_{name.replace('-', '_')}"


def _class_name(name: str) -> str:
    """Map ``my-project`` → ``MyProject`` for the starter class."""
    return "".join(
        part.capitalize()
        for part in name.replace("-", "_").split("_")
    )


def _display_name(name: str) -> str:
    """Map ``my-project`` → ``My Project`` for human-readable docstrings."""
    return name.replace("-", " ").replace("_", " ").title()


def scaffold_library(
    target_dir: Path,
    name: str,
    *,
    package_kind: str = "library",
) -> Path:
    """Create a library tree at ``target_dir / name``.

    Args:
        target_dir: Parent directory.  Created if missing.
        name: Library short name (e.g. ``"gpio"``).  Hyphens get
            converted to underscores in the import path
            (``chumicro-my-project`` → ``chumicro_my_project``).
        package_kind: ``"library"`` (default) for cross-runtime
            device packages.  Produces the standard chumicro library
            shape with no extras.  ``"workbench"`` for host-only
            CPython tools uses a workbench-flavored pyproject
            template with a ``[project.scripts]`` block (CLI entry
            point), and pulls the four ``docs/`` templates from
            ``_payloads/workbench_template/`` (no Runner pattern,
            no Memory notes, no Bundle footer link).  The rest of
            the tree (src/tests/examples/README/mkdocs) is shared
            between kinds.

    Returns:
        Path to the created library directory.

    Raises:
        LibraryAlreadyExistsError: When the target dir already
            exists.  Caller decides whether to delete + retry or
            bail.
        ValueError: When *package_kind* isn't one of the supported
            values.
    """
    if package_kind not in ("library", "workbench"):
        raise ValueError(
            f"package_kind must be 'library' or 'workbench', "
            f"got {package_kind!r}",
        )

    library_dir = target_dir / name
    if library_dir.exists():
        raise LibraryAlreadyExistsError(library_dir)

    import_name = _import_name(name)
    class_name = _class_name(name)
    display_name = _display_name(name)
    test_name = name.replace("-", "_")

    (library_dir / "src" / import_name).mkdir(parents=True)
    (library_dir / "tests").mkdir()
    (library_dir / "functional_tests").mkdir()
    (library_dir / "docs").mkdir()
    (library_dir / "examples").mkdir()
    (library_dir / "functional_tests" / ".gitkeep").touch()

    # VERSION
    (library_dir / "VERSION").write_text("0.1.0\n")

    pyproject_template = (
        "pyproject.workbench.toml.template"
        if package_kind == "workbench"
        else "pyproject.toml.template"
    )
    (library_dir / "pyproject.toml").write_text(
        _load_template(pyproject_template).format(
            name=name, import_name=import_name,
        ),
    )
    (library_dir / "mkdocs.yml").write_text(
        _load_template("mkdocs.yml.template").format(name=name),
    )
    (library_dir / "README.md").write_text(
        _load_template("readme.md.template").format(
            name=name, import_name=import_name,
        ),
    )

    # docs/.  Workbench-kind packages pull from _WORKBENCH_TEMPLATE_DIR.
    docs_template_dir = (
        _WORKBENCH_TEMPLATE_DIR
        if package_kind == "workbench"
        else _LIBRARY_TEMPLATE_DIR
    )
    (library_dir / "docs" / "index.md").write_text(
        _load_template(
            "index.md.template", template_dir=docs_template_dir,
        ).format(name=name, import_name=import_name),
    )
    (library_dir / "docs" / "guide.md").write_text(
        _load_template(
            "guide.md.template", template_dir=docs_template_dir,
        ).format(name=name, import_name=import_name),
    )
    (library_dir / "docs" / "api.md").write_text(
        _load_template(
            "api.md.template", template_dir=docs_template_dir,
        ).format(name=name, import_name=import_name),
    )
    (library_dir / "docs" / "testing.md").write_text(
        _load_template(
            "testing.md.template", template_dir=docs_template_dir,
        ).format(name=name, import_name=import_name),
    )

    (library_dir / "examples" / "basic_usage.py").write_text(
        _load_template("basic_usage.py.template").format(
            name=name,
            display_name=display_name,
            import_name=import_name,
            class_name=class_name,
        ),
    )

    # examples/helpers.py: standalone wifi-up + msgpack-decoder helper
    # for libraries whose examples bring wifi up.  No template variables.
    (library_dir / "examples" / "helpers.py").write_text(
        _load_template("helpers.py.template"),
    )

    # src/<package>/__init__.py: absolute imports only.  CircuitPython
    # RAM-mode `exec()`s library modules without a `__package__`, so
    # leading-dot relatives break at deploy.
    (library_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
        f"\n"
        f"from {import_name}.core import {class_name}\n"
        f"\n"
        f'__all__ = ["{class_name}"]\n',
    )
    (library_dir / "src" / import_name / "core.py").write_text(
        _load_template("core.py.template").format(
            name=name, class_name=class_name,
        ),
    )
    (library_dir / "src" / import_name / "testing.py").write_text(
        _load_template("testing.py.template").format(
            name=name, import_name=import_name,
        ),
    )

    # tests/.  No __init__.py, which keeps test module names from
    # colliding across libraries when pytest collects.
    (library_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the chumicro-{name} package."""\n',
    )
    (library_dir / "tests" / f"test_{test_name}.py").write_text(
        _load_template("test_library.py.template").format(
            import_name=import_name, class_name=class_name,
        ),
    )

    return library_dir
