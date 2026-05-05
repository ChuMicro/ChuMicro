"""Library scaffolder — creates a chumicro-style library tree.

External users developing their own chumicro-style libraries get
the same starter layout chumicro libraries themselves use.  The
shipped templates live alongside this module under
``_payloads/library_template/`` and travel with the wheel.

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
        └── quickstart.py

The CLI exposes this as ``python run.py new --library <name>``
(see :func:`chumicro_workspace.cli._cmd_new`).  Callers that need
finer control construct an explicit target directory and call
:func:`scaffold_library` directly.
"""

from __future__ import annotations

from pathlib import Path

#: Directory under :mod:`chumicro_workspace`'s package tree where
#: scaffolding templates live.  Resolved at import time so
#: filesystem reads stay simple — the wheel ships the same path.
_LIBRARY_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "_payloads" / "library_template"
)


class LibraryAlreadyExistsError(FileExistsError):
    """Raised when the target directory already exists.

    Carries the path so callers can construct a precise message
    without re-deriving it.  The CLI catches this and exits 1.
    """


def _load_template(filename: str) -> str:
    """Read a scaffolding template by filename.

    Templates live at :data:`_LIBRARY_TEMPLATE_DIR`.  Pure
    filesystem read — no caching, no formatting.  Caller does
    ``.format(**vars)`` on the returned string.
    """
    template_path = _LIBRARY_TEMPLATE_DIR / filename
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
            device packages — produces the standard chumicro library
            shape with no extras.  ``"workbench"`` for host-only
            CPython tools — uses a workbench-flavoured pyproject
            template with a ``[project.scripts]`` block (CLI entry
            point) and source URL pointing at ``workbench/<name>/``
            instead of ``libraries/<name>/``.  All other
            scaffolded files (src/tests/docs/examples/README/mkdocs)
            are identical between kinds — same directory shape for
            both.

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

    # Directory tree.
    (library_dir / "src" / import_name).mkdir(parents=True)
    (library_dir / "tests").mkdir()
    (library_dir / "functional_tests").mkdir()
    (library_dir / "docs").mkdir()
    (library_dir / "examples").mkdir()
    (library_dir / "functional_tests" / ".gitkeep").touch()

    # VERSION — every package starts at 0.1.0 per the SemVer policy.
    (library_dir / "VERSION").write_text("0.1.0\n")

    # Top-level config + docs.  Workbench-kind packages use a
    # different pyproject template with a CLI entry point.
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

    # docs/.
    (library_dir / "docs" / "index.md").write_text(
        _load_template("index.md.template").format(
            name=name, import_name=import_name,
        ),
    )
    (library_dir / "docs" / "guide.md").write_text(
        _load_template("guide.md.template").format(name=name),
    )
    (library_dir / "docs" / "api.md").write_text(
        _load_template("api.md.template").format(
            name=name, import_name=import_name,
        ),
    )
    (library_dir / "docs" / "testing.md").write_text(
        _load_template("testing.md.template").format(
            name=name, import_name=import_name,
        ),
    )

    # examples/quickstart.py.
    (library_dir / "examples" / "quickstart.py").write_text(
        _load_template("quickstart.py.template").format(
            name=name,
            display_name=display_name,
            import_name=import_name,
            class_name=class_name,
        ),
    )

    # src/<package>/__init__.py — absolute imports per
    # AGENTS.md non-negotiables (CircuitPython RAM-mode `exec()`s
    # library modules without a `__package__` so leading-dot
    # relatives break at deploy).  Eager imports are correct for
    # small-surface libraries; if the library grows per-runtime
    # adapters, push the lazy selection into a `_select_<project>`
    # function rather than a module-level PEP 562 `__getattr__`
    # (the deploy harness's CircuitPython RAM-mode wrapper bypasses
    # PEP 562).
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

    # tests/.  No __init__.py — keeps test module names from
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
