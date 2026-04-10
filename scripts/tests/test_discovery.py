"""Tests for discovery.py — workspace discovery, scope resolution, and helpers."""

from pathlib import Path

import pytest
from discovery import (
    ALL_PLATFORMS,
    RELEASE_RELEVANT,
    changed_libraries,
    coverage_args_for,
    detect_changed_packages,
    discover_package_dirs,
    discover_ruff_paths,
    discover_source_roots,
    filter_by_platform,
    find_package_dir,
    find_publishable_packages,
    pythonpath_environment,
    read_platforms,
    read_version,
    resolve_named_packages,
    resolve_scope,
)


class TestFindPackageDir:
    """Tests for find_package_dir."""

    def test_finds_importable_package(self, tmp_path: Path):
        """Finds the first __init__.py-bearing directory under src/."""
        source_dir = tmp_path / "src" / "chumicro_example"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").touch()
        assert find_package_dir(tmp_path) == source_dir

    def test_skips_dot_directories(self, tmp_path: Path):
        """Dot-prefixed directories are skipped."""
        hidden = tmp_path / "src" / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "__init__.py").touch()
        assert find_package_dir(tmp_path) is None

    def test_skips_egg_info(self, tmp_path: Path):
        """egg-info directories are skipped."""
        egg = tmp_path / "src" / "chumicro_example.egg-info"
        egg.mkdir(parents=True)
        (egg / "__init__.py").touch()
        assert find_package_dir(tmp_path) is None

    def test_no_src_dir(self, tmp_path: Path):
        """Returns None when there is no src/ directory."""
        assert find_package_dir(tmp_path) is None

    def test_empty_src_dir(self, tmp_path: Path):
        """Returns None when src/ exists but has no packages."""
        (tmp_path / "src").mkdir()
        assert find_package_dir(tmp_path) is None

    def test_prefers_first_alphabetically(self, tmp_path: Path):
        """When multiple packages exist, returns the first alphabetically."""
        for name in ["chumicro_beta", "chumicro_alpha"]:
            package_dir = tmp_path / "src" / name
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").touch()
        result = find_package_dir(tmp_path)
        assert result is not None
        assert result.name == "chumicro_alpha"


class TestReadPlatforms:
    """Tests for read_platforms."""

    def test_defaults_to_all_platforms(self, tmp_path: Path):
        """Missing pyproject.toml defaults to all platforms."""
        # read_platforms is cached — call with a unique path each time.
        assert read_platforms(tmp_path) == ALL_PLATFORMS

    def test_reads_platform_list(self, tmp_path: Path):
        """Reads [tool.chumicro].platforms from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.chumicro]\nplatforms = ["cpython", "micropython"]\n'
        )
        result = read_platforms(tmp_path)
        assert result == ("cpython", "micropython")

    def test_missing_section_defaults(self, tmp_path: Path):
        """Missing [tool.chumicro] section defaults to all platforms."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        result = read_platforms(tmp_path)
        assert result == ALL_PLATFORMS


class TestFilterByPlatform:
    """Tests for filter_by_platform."""

    def test_filters_correctly(self, tmp_path: Path):
        """Only packages targeting the given platform are returned."""
        # Create two fake libraries with different platform configs.
        library_a = tmp_path / "library_a"
        library_a.mkdir()
        (library_a / "pyproject.toml").write_text(
            '[tool.chumicro]\nplatforms = ["cpython"]\n'
        )

        library_b = tmp_path / "library_b"
        library_b.mkdir()
        (library_b / "pyproject.toml").write_text(
            '[tool.chumicro]\nplatforms = ["cpython", "micropython"]\n'
        )

        result = filter_by_platform([library_a, library_b], "micropython")
        assert result == [library_b]

    def test_no_pyproject_defaults_to_all(self, tmp_path: Path):
        """Libraries without pyproject.toml target all platforms."""
        library_dir = tmp_path / "library_c"
        library_dir.mkdir()
        result = filter_by_platform([library_dir], "circuitpython")
        assert result == [library_dir]


class TestDiscoverPackageDirs:
    """Tests for discover_package_dirs (uses the real workspace)."""

    def test_returns_list(self):
        """discover_package_dirs returns a non-empty list of Paths."""
        dirs = discover_package_dirs()
        assert isinstance(dirs, list)
        assert len(dirs) > 0
        assert all(isinstance(directory, Path) for directory in dirs)

    def test_all_have_pyproject(self):
        """Every discovered directory contains a pyproject.toml."""
        for package_dir in discover_package_dirs():
            assert (package_dir / "pyproject.toml").exists(), (
                f"Missing pyproject.toml: {package_dir}"
            )

    def test_includes_known_libraries(self):
        """Known libraries are discovered."""
        names = {package_dir.name for package_dir in discover_package_dirs()}
        assert "timing" in names
        assert "runner" in names


class TestDiscoverSourceRoots:
    """Tests for discover_source_roots."""

    def test_all_are_src_dirs(self):
        """Every source root ends with src/."""
        for source_root in discover_source_roots():
            assert source_root.name == "src"
            assert source_root.is_dir()


class TestDiscoverRuffPaths:
    """Tests for discover_ruff_paths."""

    def test_includes_scripts(self):
        """scripts/ is always included in the lint paths."""
        paths = discover_ruff_paths()
        assert "scripts" in paths

    def test_includes_library_source_dirs(self):
        """Library src/ directories appear in the lint paths."""
        paths = discover_ruff_paths()
        assert any("timing/src" in path for path in paths)


class TestCoverageArgsFor:
    """Tests for coverage_args_for."""

    def test_generates_cov_args(self):
        """Generates --cov arguments for libraries with importable packages."""
        dirs = discover_package_dirs()
        timing_dirs = [directory for directory in dirs if directory.name == "timing"]
        assert timing_dirs, "timing library must exist"
        args = coverage_args_for(timing_dirs)
        assert "--cov" in args
        assert any("chumicro_timing" in argument for argument in args)

    def test_empty_list(self):
        """Empty input produces empty output."""
        assert coverage_args_for([]) == []


class TestResolveNamedPackages:
    """Tests for resolve_named_packages."""

    def test_resolve_by_name(self):
        """Resolves a bare library name to its directory."""
        result = resolve_named_packages(["timing"])
        assert len(result) == 1
        assert result[0].name == "timing"

    def test_resolve_multiple(self):
        """Resolves multiple names."""
        result = resolve_named_packages(["timing", "runner"])
        names = {directory.name for directory in result}
        assert names == {"timing", "runner"}

    def test_unknown_name_returns_empty(self, capsys):
        """Unknown package name returns empty list and prints error."""
        result = resolve_named_packages(["nonexistent"])
        assert result == []
        captured = capsys.readouterr()
        assert "Unknown package: nonexistent" in captured.out


class TestFindPublishablePackages:
    """Tests for find_publishable_packages."""

    def test_returns_library_paths(self):
        """Returns relative paths to publishable libraries."""
        packages = find_publishable_packages()
        assert len(packages) > 0
        assert all(package.startswith("libraries/") for package in packages)

    def test_all_have_version_file(self):
        """Every publishable package has a VERSION file."""
        from discovery import ROOT

        for package in find_publishable_packages():
            version_path = ROOT / package / "VERSION"
            assert version_path.exists(), f"Missing VERSION: {package}"


class TestReadVersion:
    """Tests for read_version."""

    def test_reads_version_file(self, tmp_path: Path):
        """Reads version from a VERSION file."""
        (tmp_path / "VERSION").write_text("1.2.3\n")
        assert read_version(tmp_path) == "1.2.3"

    def test_missing_file_returns_none(self, tmp_path: Path):
        """Missing VERSION file returns None."""
        assert read_version(tmp_path) is None

    def test_empty_file_returns_none(self, tmp_path: Path):
        """Empty VERSION file returns None."""
        (tmp_path / "VERSION").write_text("")
        assert read_version(tmp_path) is None

    def test_whitespace_only_returns_none(self, tmp_path: Path):
        """Whitespace-only VERSION file returns None."""
        (tmp_path / "VERSION").write_text("  \n  \n")
        assert read_version(tmp_path) is None


class TestChangedLibraries:
    """Tests for changed_libraries — file path classification."""

    def test_src_change_detected(self, monkeypatch):
        """A change under libraries/<name>/src/ is release-relevant."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: ["libraries/timing/src/chumicro_timing/core.py"],
        )
        result = changed_libraries("origin/main")
        assert result == {"timing"}

    def test_pyproject_change_detected(self, monkeypatch):
        """A change to libraries/<name>/pyproject.toml is release-relevant."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: ["libraries/runner/pyproject.toml"],
        )
        result = changed_libraries("origin/main")
        assert result == {"runner"}

    def test_test_change_not_detected(self, monkeypatch):
        """A change under libraries/<name>/tests/ is NOT release-relevant."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: ["libraries/timing/tests/test_ticks.py"],
        )
        result = changed_libraries("origin/main")
        assert result == set()

    def test_docs_change_not_detected(self, monkeypatch):
        """A change under libraries/<name>/docs/ is NOT release-relevant."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: ["libraries/timing/docs/guide.md"],
        )
        result = changed_libraries("origin/main")
        assert result == set()

    def test_multiple_libraries(self, monkeypatch):
        """Changes across multiple libraries are all detected."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/runner/src/chumicro_runner/core.py",
            ],
        )
        result = changed_libraries("origin/main")
        assert result == {"timing", "runner"}

    def test_non_library_paths_ignored(self, monkeypatch):
        """Paths outside libraries/ are ignored."""
        monkeypatch.setattr(
            "discovery.changed_files",
            lambda _base: ["scripts/run.py", "README.md"],
        )
        result = changed_libraries("origin/main")
        assert result == set()


class TestReleaseRelevant:
    """Verify the RELEASE_RELEVANT constant."""

    def test_expected_entries(self):
        """RELEASE_RELEVANT contains the expected set."""
        assert RELEASE_RELEVANT == {"src", "pyproject.toml"}


class TestDetectChangedPackages:
    """Tests for detect_changed_packages."""

    def test_infrastructure_change_returns_none(self, monkeypatch):
        """Changes to scripts/ trigger all-packages testing."""
        monkeypatch.setattr(
            "discovery.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "scripts/run.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_conftest_change_returns_none(self, monkeypatch):
        """Changes to root conftest.py trigger all-packages testing."""
        monkeypatch.setattr(
            "discovery.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "conftest.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_github_change_returns_none(self, monkeypatch):
        """Changes to .github/ trigger all-packages testing."""
        monkeypatch.setattr(
            "discovery.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": ".github/workflows/ci.yml\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_no_changes_returns_none(self, monkeypatch):
        """No changed files returns None (run everything)."""
        monkeypatch.setattr(
            "discovery.subprocess.run",
            lambda *_args, **_kwargs: type("R", (), {"returncode": 0, "stdout": ""})(),
        )
        assert detect_changed_packages() is None

    def test_library_change_detected(self, monkeypatch):
        """Library changes return the affected package directories."""
        monkeypatch.setattr(
            "discovery.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (),
                {"returncode": 0, "stdout": "libraries/timing/src/chumicro_timing/core.py\n"},
            )(),
        )
        result = detect_changed_packages()
        assert result is not None
        names = [package_dir.name for package_dir in result]
        assert "timing" in names

    def test_git_unavailable_returns_none(self, monkeypatch):
        """When git is not available, returns None."""
        def raise_not_found(*_args, **_kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("discovery.subprocess.run", raise_not_found)
        assert detect_changed_packages() is None


class TestResolveScope:
    """Tests for resolve_scope."""

    def test_all_packages(self):
        """--all returns all discovered packages."""
        result = resolve_scope(all_packages=True)
        assert len(result) > 0
        names = {package_dir.name for package_dir in result}
        assert "timing" in names

    def test_specific_libraries(self):
        """--libraries returns only the named packages."""
        result = resolve_scope(libraries="timing")
        assert len(result) == 1
        assert result[0].name == "timing"

    def test_unknown_library_exits(self):
        """Unknown library name raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_scope(libraries="nonexistent")


class TestPythonpathEnvironment:
    """Tests for pythonpath_environment."""

    def test_returns_dict(self):
        """Returns a dict with PYTHONPATH set."""
        environment = pythonpath_environment()
        assert isinstance(environment, dict)
        assert "PYTHONPATH" in environment

    def test_includes_source_roots(self):
        """PYTHONPATH contains library source roots."""
        environment = pythonpath_environment()
        pythonpath = environment["PYTHONPATH"]
        assert "timing" in pythonpath

    def test_preserves_existing_path(self, monkeypatch):
        """Existing PYTHONPATH entries are preserved."""
        monkeypatch.setenv("PYTHONPATH", "/existing/path")
        environment = pythonpath_environment()
        assert "/existing/path" in environment["PYTHONPATH"]

    def test_includes_path(self):
        """PATH from os.environ is preserved."""
        environment = pythonpath_environment()
        assert "PATH" in environment

