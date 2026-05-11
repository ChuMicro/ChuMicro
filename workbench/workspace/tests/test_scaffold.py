"""Tests for the library scaffolder."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.scaffold import (
    LibraryAlreadyExistsError,
    _class_name,
    _display_name,
    _import_name,
    scaffold_library,
)


class TestNameHelpers:
    """Tiny helpers map a hyphenated short-name to its derived forms."""

    def test_import_name_underscores(self) -> None:
        assert _import_name("gpio") == "chumicro_gpio"
        assert _import_name("my-project") == "chumicro_my_project"
        assert _import_name("my_project") == "chumicro_my_project"

    def test_class_name_camel_case(self) -> None:
        assert _class_name("gpio") == "Gpio"
        assert _class_name("my-project") == "MyProject"
        assert _class_name("my_project") == "MyProject"

    def test_display_name_title_case(self) -> None:
        assert _display_name("gpio") == "Gpio"
        assert _display_name("my-project") == "My Project"
        assert _display_name("my_project") == "My Project"


class TestScaffoldLibrary:
    def test_creates_canonical_layout(self, tmp_path: Path) -> None:
        created = scaffold_library(tmp_path / "libraries", "gpio")
        # Returned path matches the new tree.
        assert created == tmp_path / "libraries" / "gpio"
        assert created.is_dir()
        # Top-level file shape.
        assert (created / "VERSION").read_text() == "0.1.0\n"
        assert (created / "pyproject.toml").is_file()
        assert (created / "mkdocs.yml").is_file()
        assert (created / "README.md").is_file()
        # src/<package>/.
        package_dir = created / "src" / "chumicro_gpio"
        assert (package_dir / "__init__.py").is_file()
        assert (package_dir / "core.py").is_file()
        assert (package_dir / "testing.py").is_file()
        # tests/.
        assert (created / "tests" / "conftest.py").is_file()
        assert (created / "tests" / "test_gpio.py").is_file()
        # functional_tests/ + .gitkeep so empty dir survives git.
        assert (created / "functional_tests" / ".gitkeep").is_file()
        # docs/.
        for doc_filename in ("index.md", "guide.md", "api.md", "testing.md"):
            assert (created / "docs" / doc_filename).is_file()
        # examples/.
        assert (created / "examples" / "basic_usage.py").is_file()
        helpers_text = (created / "examples" / "helpers.py").read_text()
        assert "def wifi_up" in helpers_text
        assert "def runtime_config" in helpers_text
        assert "def _msgpack_unpack" in helpers_text

    def test_init_py_imports_starter_class(self, tmp_path: Path) -> None:
        """The package's __init__.py wires `from <pkg>.core import <Class>`."""
        created = scaffold_library(tmp_path / "libraries", "gpio")
        init_text = (created / "src" / "chumicro_gpio" / "__init__.py").read_text()
        assert "from chumicro_gpio.core import Gpio" in init_text
        assert '__all__ = ["Gpio"]' in init_text

    def test_hyphen_name_translates_to_snake_case_imports(
        self, tmp_path: Path,
    ) -> None:
        """`my-project` → package `chumicro_my_project`, class `MyProject`."""
        created = scaffold_library(tmp_path / "libraries", "my-project")
        # Filesystem uses hyphenated short-name (chumicro convention).
        assert created.name == "my-project"
        # Package + module name use snake_case.
        package_init = (
            created / "src" / "chumicro_my_project" / "__init__.py"
        )
        assert package_init.is_file()
        text = package_init.read_text()
        assert "from chumicro_my_project.core import MyProject" in text
        # Test file uses snake_case basename.
        assert (created / "tests" / "test_my_project.py").is_file()

    def test_creates_target_parent_when_missing(self, tmp_path: Path) -> None:
        """Parent dirs are auto-created — no need to pre-mkdir libraries/."""
        target_parent = tmp_path / "deep" / "nested" / "libraries"
        created = scaffold_library(target_parent, "gpio")
        assert created.is_dir()
        assert target_parent.is_dir()

    def test_existing_target_raises(self, tmp_path: Path) -> None:
        scaffold_library(tmp_path / "libraries", "gpio")
        with pytest.raises(LibraryAlreadyExistsError) as caught:
            scaffold_library(tmp_path / "libraries", "gpio")
        assert "gpio" in str(caught.value)

    def test_workbench_kind_scaffolds_workbench_flavored_docs(
        self, tmp_path: Path,
    ) -> None:
        """`package_kind="workbench"` pulls docs from the workbench template.

        Workbench packages aren't cross-runtime and don't ship via
        bundles, so their docs should not carry the library shape's
        Runner pattern / Memory notes sections or the Bundle footer
        link.  Also call out that the source URL points at
        ``workbench/<name>/``, not ``libraries/<name>/``.
        """
        created = scaffold_library(
            tmp_path / "workbench", "trinket", package_kind="workbench",
        )
        guide_text = (created / "docs" / "guide.md").read_text()
        index_text = (created / "docs" / "index.md").read_text()
        api_text = (created / "docs" / "api.md").read_text()
        testing_text = (created / "docs" / "testing.md").read_text()

        # Library-flavoured headings + footer link must be absent.
        # (The workbench guide's GENERATION INSTRUCTIONS block names
        # the missing sections by their bare titles, so match the
        # heading form explicitly.)
        for doc_text in (guide_text, index_text, api_text, testing_text):
            assert "## Runner pattern" not in doc_text
            assert "## Memory notes" not in doc_text
            assert "ChuMicro-Bundle" not in doc_text

        # Workbench source URLs replace the library path.
        for doc_text in (guide_text, index_text, api_text, testing_text):
            assert "tree/main/workbench/trinket" in doc_text
            assert "tree/main/libraries/trinket" not in doc_text

        # Index footer relabel: "Libraries" → "Packages".
        assert "All ChuMicro Packages" in index_text
        assert "All ChuMicro Libraries" not in index_text

    def test_library_kind_keeps_library_flavored_docs(
        self, tmp_path: Path,
    ) -> None:
        """Default `package_kind="library"` keeps the library doc shape."""
        created = scaffold_library(tmp_path / "libraries", "gpio")
        guide_text = (created / "docs" / "guide.md").read_text()
        index_text = (created / "docs" / "index.md").read_text()

        # Library shape includes Runner pattern + Memory notes
        # sections and the Bundle footer link.
        assert "Runner pattern" in guide_text
        assert "Memory notes" in guide_text
        assert "ChuMicro-Bundle" in guide_text

        # Library source URL.
        assert "tree/main/libraries/gpio" in guide_text
        assert "All ChuMicro Libraries" in index_text
