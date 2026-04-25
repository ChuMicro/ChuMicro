"""Tests for workspace.py — workspace discovery, scope resolution, and helpers."""

from pathlib import Path

import pytest
from workspace import (
    ALL_PLATFORMS,
    GITHUB_ORG,
    PUBLISHABLE_ROOTS,
    RELEASE_RELEVANT,
    changed_publishable_packages,
    coverage_args_for,
    detect_changed_packages,
    discover_doc_dirs,
    discover_library_dirs,
    discover_package_dirs,
    discover_ruff_paths,
    discover_source_roots,
    discover_workbench_dirs,
    filter_by_platform,
    find_package_dir,
    find_publishable_packages,
    is_ref_reachable,
    load_tomllib,
    order_libraries_by_dependency,
    pythonpath_environment,
    read_platforms,
    read_pyproject_description,
    read_version,
    resolve_named_packages,
    resolve_scope,
)


class TestLoadTomllib:
    """Tests for load_tomllib."""

    def test_returns_module(self):
        """Returns a module with a load function."""
        tomllib = load_tomllib()
        assert hasattr(tomllib, "load")

    def test_idempotent(self):
        """Calling twice returns the same module."""
        first = load_tomllib()
        second = load_tomllib()
        assert first is second


class TestGithubOrg:
    """Tests for the GITHUB_ORG constant."""

    def test_value(self):
        """GITHUB_ORG is the expected string."""
        assert GITHUB_ORG == "ChuMicro"


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
        """Returns relative paths to publishable packages under libraries/ or workbench/."""
        packages = find_publishable_packages()
        assert len(packages) > 0
        assert all(
            package.startswith(("libraries/", "workbench/")) for package in packages
        )

    def test_all_have_version_file(self):
        """Every publishable package has a VERSION file."""
        from workspace import ROOT

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


class TestChangedPublishablePackages:
    """Tests for changed_publishable_packages — file path classification."""

    def test_library_src_change_detected(self, monkeypatch):
        """A change under libraries/<name>/src/ is release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: ["libraries/timing/src/chumicro_timing/core.py"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "timing")}

    def test_library_pyproject_change_detected(self, monkeypatch):
        """A change to libraries/<name>/pyproject.toml is release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: ["libraries/runner/pyproject.toml"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "runner")}

    def test_workbench_src_change_detected(self, monkeypatch):
        """A change under workbench/<name>/src/ is release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: ["workbench/deploy/src/chumicro_deploy/core.py"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("workbench", "deploy")}

    def test_workbench_pyproject_change_detected(self, monkeypatch):
        """A change to workbench/<name>/pyproject.toml is release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: ["workbench/repl/pyproject.toml"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("workbench", "repl")}

    def test_test_change_not_detected(self, monkeypatch):
        """A change under <root>/<name>/tests/ is NOT release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: [
                "libraries/timing/tests/test_ticks.py",
                "workbench/deploy/tests/test_session.py",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == set()

    def test_docs_change_not_detected(self, monkeypatch):
        """A change under <root>/<name>/docs/ is NOT release-relevant."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: ["libraries/timing/docs/guide.md"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == set()

    def test_mixed_roots(self, monkeypatch):
        """Changes across libraries/ and workbench/ are both detected."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "workbench/deploy/src/chumicro_deploy/core.py",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "timing"), ("workbench", "deploy")}

    def test_support_paths_ignored(self, monkeypatch):
        """Paths under support/ are not publishable and are ignored."""
        monkeypatch.setattr(
            "workspace.changed_files",
            lambda _base: [
                "support/test_harness/src/test_harness/core.py",
                "scripts/run.py",
                "README.md",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == set()


class TestReleaseRelevant:
    """Verify the RELEASE_RELEVANT constant."""

    def test_expected_entries(self):
        """RELEASE_RELEVANT contains the expected set."""
        assert RELEASE_RELEVANT == {"src", "pyproject.toml"}


class TestPublishableRoots:
    """Verify the PUBLISHABLE_ROOTS constant."""

    def test_expected_entries(self):
        """PUBLISHABLE_ROOTS covers libraries/ and workbench/."""
        assert PUBLISHABLE_ROOTS == ("libraries", "workbench")


class TestDetectChangedPackages:
    """Tests for detect_changed_packages."""

    def test_infrastructure_change_returns_none(self, monkeypatch):
        """Changes to scripts/ trigger all-packages testing."""
        monkeypatch.setattr(
            "workspace.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "scripts/run.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_conftest_change_returns_none(self, monkeypatch):
        """Changes to root conftest.py trigger all-packages testing."""
        monkeypatch.setattr(
            "workspace.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "conftest.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_github_change_returns_none(self, monkeypatch):
        """Changes to .github/ trigger all-packages testing."""
        monkeypatch.setattr(
            "workspace.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": ".github/workflows/ci.yml\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_no_changes_returns_none(self, monkeypatch):
        """No changed files returns None (run everything)."""
        monkeypatch.setattr(
            "workspace.subprocess.run",
            lambda *_args, **_kwargs: type("R", (), {"returncode": 0, "stdout": ""})(),
        )
        assert detect_changed_packages() is None

    def test_library_change_detected(self, monkeypatch):
        """Library changes return the affected package directories."""
        monkeypatch.setattr(
            "workspace.subprocess.run",
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

        monkeypatch.setattr("workspace.subprocess.run", raise_not_found)
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


class TestDiscoverLibraryDirs:
    """Tests for discover_library_dirs."""

    def test_returns_list(self):
        """discover_library_dirs returns a non-empty list of Paths."""
        dirs = discover_library_dirs()
        assert isinstance(dirs, list)
        assert len(dirs) > 0

    def test_all_under_libraries(self):
        """Every returned directory is under libraries/."""
        for library_dir in discover_library_dirs():
            assert library_dir.parent.name == "libraries"

    def test_excludes_support(self):
        """Support packages are not included."""
        names = {library_dir.name for library_dir in discover_library_dirs()}
        # support packages like test_harness should not appear
        support_names = {
            package_dir.name for package_dir in discover_package_dirs()
            if package_dir.parent.name == "support"
        }
        assert names.isdisjoint(support_names)

    def test_includes_known_libraries(self):
        """Known libraries are discovered."""
        names = {library_dir.name for library_dir in discover_library_dirs()}
        assert "timing" in names
        assert "runner" in names

    def test_subset_of_discover_package_dirs(self):
        """Results are a subset of discover_package_dirs."""
        all_dirs = set(str(directory) for directory in discover_package_dirs())
        library_dirs = set(str(directory) for directory in discover_library_dirs())
        assert library_dirs.issubset(all_dirs)


class TestDiscoverWorkbenchDirs:
    """Tests for discover_workbench_dirs."""

    def test_returns_list(self):
        """discover_workbench_dirs returns a list of Paths."""
        dirs = discover_workbench_dirs()
        assert isinstance(dirs, list)

    def test_all_under_workbench(self):
        """Every returned directory is under workbench/."""
        for workbench_dir in discover_workbench_dirs():
            assert workbench_dir.parent.name == "workbench"

    def test_excludes_libraries(self):
        """Library packages are not included."""
        names = {workbench_dir.name for workbench_dir in discover_workbench_dirs()}
        library_names = {library_dir.name for library_dir in discover_library_dirs()}
        assert names.isdisjoint(library_names)

    def test_subset_of_discover_package_dirs(self):
        """Results are a subset of discover_package_dirs."""
        all_dirs = {str(directory) for directory in discover_package_dirs()}
        workbench_dirs = {str(directory) for directory in discover_workbench_dirs()}
        assert workbench_dirs.issubset(all_dirs)


class TestReadPyprojectDescription:
    """Tests for read_pyproject_description."""

    def test_reads_from_pyproject(self):
        """Reads the description field from a real library directory."""
        from workspace import ROOT

        library_dir = ROOT / "libraries" / "timing"
        description = read_pyproject_description(library_dir)
        assert description
        assert "**" not in description

    def test_returns_empty_for_missing_field(self, tmp_path: Path):
        """Returns empty string when description is absent."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text("[project]\nname = 'test'\n")
        assert read_pyproject_description(tmp_path) == ""

    def test_returns_empty_for_missing_pyproject(self, tmp_path: Path):
        """Returns empty string when pyproject.toml does not exist."""
        assert read_pyproject_description(tmp_path) == ""

    def test_falls_back_to_readme(self, tmp_path: Path):
        """Falls back to README.md when description is empty."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        (tmp_path / "README.md").write_text("# My Library\n\nA great library.\n")
        description = read_pyproject_description(tmp_path)
        assert description == "A great library."


class TestDiscoverDocDirs:
    """Tests for discover_doc_dirs."""

    def test_returns_list(self):
        """discover_doc_dirs returns a non-empty list."""
        dirs = discover_doc_dirs()
        assert isinstance(dirs, list)
        assert len(dirs) > 0

    def test_all_have_mkdocs(self):
        """Every returned directory contains an mkdocs.yml."""
        for doc_dir in discover_doc_dirs():
            assert (doc_dir / "mkdocs.yml").exists()

    def test_includes_known_libraries(self):
        """Known libraries with docs are discovered."""
        names = {doc_dir.name for doc_dir in discover_doc_dirs()}
        assert "timing" in names

    def test_includes_workbench_packages(self):
        """Workbench packages with mkdocs.yml are discovered by default."""
        names = {doc_dir.name for doc_dir in discover_doc_dirs()}
        assert "deploy" in names

    def test_accepts_custom_package_dirs(self, tmp_path: Path):
        """Accepts a custom list of package dirs."""
        library_dir = tmp_path / "mylib"
        library_dir.mkdir()
        (library_dir / "mkdocs.yml").touch()
        result = discover_doc_dirs([library_dir])
        assert result == [library_dir]

    def test_filters_dirs_without_mkdocs(self, tmp_path: Path):
        """Directories without mkdocs.yml are excluded."""
        library_dir = tmp_path / "nodocs"
        library_dir.mkdir()
        result = discover_doc_dirs([library_dir])
        assert result == []


class TestIsRefReachable:
    """Tests for is_ref_reachable."""

    def test_head_is_reachable(self):
        """HEAD is always reachable in a git repo."""
        assert is_ref_reachable("HEAD") is True

    def test_nonexistent_reference(self):
        """A clearly nonexistent ref is not reachable."""
        assert is_ref_reachable("nonexistent-ref-abc123xyz") is False


class TestOrderLibrariesByDependency:
    """Tests for order_libraries_by_dependency topological sort."""

    def test_no_deps_preserves_input_order(self):
        """Libraries with no deps are returned in input order."""
        result = order_libraries_by_dependency(
            ["a", "b", "c"], deps_for=lambda _: [],
        )
        assert result == ["a", "b", "c"]

    def test_dep_listed_first(self):
        """A library is placed after the libraries it depends on."""
        deps = {"runner": ["timing"]}
        result = order_libraries_by_dependency(
            ["runner", "timing"], deps_for=lambda name: deps.get(name, []),
        )
        assert result.index("timing") < result.index("runner")

    def test_dep_chain(self):
        """Multi-link chains are ordered correctly."""
        deps = {"c": ["b"], "b": ["a"]}
        result = order_libraries_by_dependency(
            ["c", "b", "a"], deps_for=lambda name: deps.get(name, []),
        )
        assert result == ["a", "b", "c"]

    def test_external_deps_ignored(self):
        """Dependencies outside the requested set are skipped silently."""
        deps = {"timing": ["external_thing"]}
        result = order_libraries_by_dependency(
            ["timing"], deps_for=lambda name: deps.get(name, []),
        )
        assert result == ["timing"]

    def test_diamond_dependencies(self):
        """A library depended on by two others appears once, before both."""
        deps = {"top": ["left", "right"], "left": ["bottom"], "right": ["bottom"]}
        result = order_libraries_by_dependency(
            ["top", "left", "right", "bottom"],
            deps_for=lambda name: deps.get(name, []),
        )
        assert result.count("bottom") == 1
        assert result.index("bottom") < result.index("left")
        assert result.index("bottom") < result.index("right")
        assert result.index("left") < result.index("top")
        assert result.index("right") < result.index("top")

    def test_cycle_raises(self):
        """A dependency cycle raises ValueError."""
        deps = {"a": ["b"], "b": ["a"]}
        with pytest.raises(ValueError, match="cycle"):
            order_libraries_by_dependency(
                ["a", "b"], deps_for=lambda name: deps.get(name, []),
            )

    def test_self_dependency_is_a_cycle(self):
        """A library that lists itself as a dep raises ValueError."""
        with pytest.raises(ValueError, match="cycle"):
            order_libraries_by_dependency(["a"], deps_for=lambda _: ["a"])

    def test_empty_input(self):
        """Empty input returns empty output."""
        assert order_libraries_by_dependency([], deps_for=lambda _: []) == []
