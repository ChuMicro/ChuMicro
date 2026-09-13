"""Tests for scaffold.py — library scaffolding."""

from pathlib import Path

from new_library_scaffold import _scaffold_library


def _make_root(tmp_path: Path, monkeypatch, parent: str = "libraries") -> None:
    """Point the scaffolder at a fake repo root with a LICENSE to copy."""
    monkeypatch.setattr("new_library_scaffold.ROOT", tmp_path)
    (tmp_path / "LICENSE").write_text("MIT License\n")
    (tmp_path / parent).mkdir(parents=True)


class TestScaffoldLibrary:
    """Tests for _scaffold_library."""

    def test_creates_expected_structure(self, tmp_path: Path, monkeypatch):
        """Scaffolding creates the full directory tree."""
        _make_root(tmp_path, monkeypatch)

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
        assert (library_dir / "examples" / "basic_usage.py").exists()
        assert (library_dir / "functional_tests" / ".gitkeep").exists()

    def test_copies_the_root_license(self, tmp_path: Path, monkeypatch):
        """The package carries the repo root LICENSE, byte for byte."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("example")
        packaged = (tmp_path / "libraries" / "example" / "LICENSE").read_bytes()
        assert packaged == (tmp_path / "LICENSE").read_bytes()

    def test_version_starts_at_0_1_0(self, tmp_path: Path, monkeypatch):
        """VERSION file starts at 0.1.0."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("example")
        version = (tmp_path / "libraries" / "example" / "VERSION").read_text()
        assert version.strip() == "0.1.0"

    def test_pyproject_contains_name(self, tmp_path: Path, monkeypatch):
        """pyproject.toml contains the library name."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("mylib")
        pyproject = (tmp_path / "libraries" / "mylib" / "pyproject.toml").read_text()
        assert 'name = "chumicro-mylib"' in pyproject

    def test_mono_repo_scaffold_is_branded(self, tmp_path: Path, monkeypatch):
        """The mono-repo wrapper stamps ChuMicro identity into its scaffolds.

        Unlike a downstream ``chumicro-workspace new --library`` run (which
        gets the neutral self-owned default), the mono-repo's own new-library
        flow points README + pyproject at the ChuMicro repos where these
        libraries live, so the emitted package resolves its Homepage / Source
        / bundle links.
        """
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("mylib")
        library_dir = tmp_path / "libraries" / "mylib"
        readme = (library_dir / "README.md").read_text()
        pyproject = (library_dir / "pyproject.toml").read_text()
        assert "chumicro_tip.png" in readme
        assert "Part of the [ChuMicro]" in readme
        assert "Homepage = \"https://github.com/ChuMicro/ChuMicro\"" in pyproject

    def test_init_exports_class(self, tmp_path: Path, monkeypatch):
        """__init__.py exports the generated class name."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("my-thing")
        init_content = (
            tmp_path / "libraries" / "my-thing" / "src" / "chumicro_my_thing" / "__init__.py"
        ).read_text()
        assert "MyThing" in init_content
        # Absolute import — TID252 in scope of libraries/*/src per
        # AGENTS.md non-negotiable.
        assert "from chumicro_my_thing.core import MyThing" in init_content

    def test_existing_directory_fails(self, tmp_path: Path, monkeypatch, capsys):
        """Scaffolding fails if the library directory already exists."""
        _make_root(tmp_path, monkeypatch)
        (tmp_path / "libraries" / "existing").mkdir()

        result = _scaffold_library("existing")
        assert result == 1
        assert "already exists" in capsys.readouterr().out

    def test_hyphenated_name(self, tmp_path: Path, monkeypatch):
        """Hyphenated library names are converted to underscores in imports."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("data-store")
        assert (
            tmp_path / "libraries" / "data-store" / "src" / "chumicro_data_store" / "__init__.py"
        ).exists()

    def test_workbench_scaffolds_under_workbench_dir(
        self, tmp_path: Path, monkeypatch,
    ):
        """--workbench scaffolds under workbench/ with the host-tool pyproject.

        Parity with the workspace CLI's ``new --workbench``: same
        scaffolder, workbench parent + ``package_kind="workbench"``,
        which yields the CLI-entry-point ``[project.scripts]`` block.
        """
        _make_root(tmp_path, monkeypatch, parent="workbench")

        result = _scaffold_library("mytool", workbench=True)
        assert result == 0

        package_dir = tmp_path / "workbench" / "mytool"
        assert package_dir.is_dir()
        assert not (tmp_path / "libraries").exists()
        pyproject = (package_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-mytool"' in pyproject
        assert "[project.scripts]" in pyproject

    def test_test_file_has_tests(self, tmp_path: Path, monkeypatch):
        """Generated test file contains test methods."""
        _make_root(tmp_path, monkeypatch)

        _scaffold_library("example")
        test_content = (
            tmp_path / "libraries" / "example" / "tests" / "test_example.py"
        ).read_text()
        assert "def test_default_value" in test_content
        assert "def test_update" in test_content
