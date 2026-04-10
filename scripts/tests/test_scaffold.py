"""Tests for scaffold.py — library scaffolding."""

from pathlib import Path

from scaffold import _scaffold_library


class TestScaffoldLibrary:
    """Tests for _scaffold_library."""

    def test_creates_expected_structure(self, tmp_path: Path, monkeypatch):
        """Scaffolding creates the full directory tree."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        result = _scaffold_library("example")
        assert result == 0

        library_dir = tmp_path / "libraries" / "example"
        assert library_dir.is_dir()
        assert (library_dir / "VERSION").exists()
        assert (library_dir / "pyproject.toml").exists()
        assert (library_dir / "mkdocs.yml").exists()
        assert (library_dir / "README.md").exists()
        assert (library_dir / "src" / "chumicro_example" / "__init__.py").exists()
        assert (library_dir / "src" / "chumicro_example" / "core.py").exists()
        assert (library_dir / "src" / "chumicro_example" / "testing.py").exists()
        assert (library_dir / "tests" / "conftest.py").exists()
        assert (library_dir / "tests" / "test_example.py").exists()
        assert (library_dir / "docs" / "index.md").exists()
        assert (library_dir / "docs" / "guide.md").exists()
        assert (library_dir / "docs" / "api.md").exists()
        assert (library_dir / "docs" / "testing.md").exists()
        assert (library_dir / "examples" / "quickstart.py").exists()
        assert (library_dir / "functional_tests" / ".gitkeep").exists()

    def test_version_starts_at_0_1_0(self, tmp_path: Path, monkeypatch):
        """VERSION file starts at 0.1.0."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        _scaffold_library("example")
        version = (tmp_path / "libraries" / "example" / "VERSION").read_text()
        assert version.strip() == "0.1.0"

    def test_pyproject_contains_name(self, tmp_path: Path, monkeypatch):
        """pyproject.toml contains the library name."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        _scaffold_library("mylib")
        pyproject = (tmp_path / "libraries" / "mylib" / "pyproject.toml").read_text()
        assert 'name = "chumicro-mylib"' in pyproject

    def test_init_exports_class(self, tmp_path: Path, monkeypatch):
        """__init__.py exports the generated class name."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        _scaffold_library("my-thing")
        init_content = (
            tmp_path / "libraries" / "my-thing" / "src" / "chumicro_my_thing" / "__init__.py"
        ).read_text()
        assert "MyThing" in init_content
        assert "from .core import MyThing" in init_content

    def test_existing_directory_fails(self, tmp_path: Path, monkeypatch, capsys):
        """Scaffolding fails if the library directory already exists."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries" / "existing").mkdir(parents=True)

        result = _scaffold_library("existing")
        assert result == 1
        assert "already exists" in capsys.readouterr().out

    def test_hyphenated_name(self, tmp_path: Path, monkeypatch):
        """Hyphenated library names are converted to underscores in imports."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        _scaffold_library("data-store")
        assert (
            tmp_path / "libraries" / "data-store" / "src" / "chumicro_data_store" / "__init__.py"
        ).exists()

    def test_test_file_has_tests(self, tmp_path: Path, monkeypatch):
        """Generated test file contains test methods."""
        monkeypatch.setattr("scaffold.ROOT", tmp_path)
        (tmp_path / "libraries").mkdir()

        _scaffold_library("example")
        test_content = (
            tmp_path / "libraries" / "example" / "tests" / "test_example.py"
        ).read_text()
        assert "def test_default_value" in test_content
        assert "def test_update" in test_content

