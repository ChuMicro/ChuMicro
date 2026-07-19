"""Tests for repo_layout.py — workspace discovery, scope resolution, and helpers.

Every test that touches workspace state runs against a synthetic
workspace materialized under ``tmp_path``: the ``synthetic_workspace``
fixture stands up a controlled set of fake packages (``libraries/lib_a``,
``libraries/lib_b``, ``workbench/tool_x``, ``support/helper``) and pins
``repo_layout.ROOT`` to the temp tree.  No test reads the real on-disk
state of any real package — that would couple test outcomes to
whichever packages happened to live in the workspace on the day the
test was written, and the same partial-mock smell that broke
``test_check_version`` (commit ``708cf21``) would silently re-emerge
here as soon as a real package was renamed or a new one added.
"""

from pathlib import Path

import pytest
import repo_layout
from repo_layout import (
    ALL_PLATFORMS,
    GITHUB_ORG,
    PARKED_MARKER,
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
    effective_diff_base,
    filter_by_platform,
    find_package_dir,
    find_publishable_packages,
    is_parked,
    is_ref_reachable,
    load_tomllib,
    order_libraries_by_dependency,
    pythonpath_environment,
    read_parked_reason,
    read_platforms,
    read_pyproject_description,
    read_version,
    resolve_named_packages,
    resolve_scope,
)


@pytest.fixture
def synthetic_workspace(tmp_path: Path, monkeypatch):
    """Materialize a synthetic workspace under ``tmp_path`` and pin
    ``repo_layout.ROOT`` to it.

    The layout (intentionally diverse so tests can exercise filters):

    * ``libraries/lib_a/`` — pyproject + ``src/chumicro_lib_a/`` +
      ``VERSION`` (``1.0.0``) + ``mkdocs.yml`` + ``tests/``
    * ``libraries/lib_b/`` — pyproject + ``src/chumicro_lib_b/`` +
      ``VERSION`` (``0.0.0``) — pre-release floor, no docs
    * ``workbench/tool_x/`` — pyproject + ``src/chumicro_tool_x/`` +
      ``VERSION`` (``0.5.0``) + ``mkdocs.yml``
    * ``support/helper/`` — pyproject + ``src/chumicro_helper/`` (no
      VERSION; a support package is held out of the publish set until it
      carries one, Decision 0111 — so ``helper`` stays editable-only)

    Clears ``repo_layout._package_dirs_cache`` so the cached real-workspace
    discovery from a prior test (or other code path) doesn't bleed in.
    """
    layout = [
        ("libraries", "lib_a", "1.0.0", True, True),
        ("libraries", "lib_b", "0.0.0", False, False),
        ("workbench", "tool_x", "0.5.0", True, False),
        ("support", "helper", None, False, False),
    ]
    for parent, name, version, with_mkdocs, with_tests in layout:
        package_dir = tmp_path / parent / name
        source_dir = package_dir / "src" / f"chumicro_{name}"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").touch()
        (package_dir / "pyproject.toml").write_text(
            f'[project]\nname = "chumicro-{name}"\n'
            f'description = "Synthetic {name} package."\n',
        )
        if version is not None:
            (package_dir / "VERSION").write_text(f"{version}\n")
        if with_mkdocs:
            (package_dir / "mkdocs.yml").touch()
        if with_tests:
            (package_dir / "tests").mkdir()

    monkeypatch.setattr(repo_layout, "ROOT", tmp_path)
    monkeypatch.setattr(repo_layout, "_package_dirs_cache", None)

    return tmp_path


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
    """Tests for discover_package_dirs against a synthetic repo_layout."""

    def test_returns_list_of_paths(self, synthetic_workspace):
        """Returns a list of Paths covering every synthetic package."""
        dirs = discover_package_dirs()
        assert isinstance(dirs, list)
        assert all(isinstance(directory, Path) for directory in dirs)
        names = {directory.name for directory in dirs}
        assert names == {"lib_a", "lib_b", "tool_x", "helper"}

    def test_filters_to_pyproject_dirs(self, synthetic_workspace):
        """Only directories with a pyproject.toml are returned.

        Adds an extra directory under ``libraries/`` without a
        ``pyproject.toml`` and confirms the discovery filter omits it.
        """
        (synthetic_workspace / "libraries" / "no_pyproject").mkdir()
        names = {directory.name for directory in discover_package_dirs()}
        assert "no_pyproject" not in names

    def test_skips_missing_root_directories(
        self, tmp_path: Path, monkeypatch,
    ):
        """Missing ``support/`` / ``libraries/`` / ``workbench/`` roots
        are silently skipped — fresh workspaces start with subsets."""
        (tmp_path / "libraries" / "lone").mkdir(parents=True)
        (tmp_path / "libraries" / "lone" / "pyproject.toml").touch()

        monkeypatch.setattr(repo_layout, "ROOT", tmp_path)
        monkeypatch.setattr(repo_layout, "_package_dirs_cache", None)

        names = {directory.name for directory in discover_package_dirs()}
        assert names == {"lone"}


class TestDiscoverSourceRoots:
    """Tests for discover_source_roots."""

    def test_all_are_src_dirs(self, synthetic_workspace):
        """Every source root ends with ``src/`` and exists on disk."""
        for source_root in discover_source_roots():
            assert source_root.name == "src"
            assert source_root.is_dir()


class TestDiscoverRuffPaths:
    """Tests for discover_ruff_paths."""

    def test_includes_scripts(self, synthetic_workspace):
        """``scripts`` is always included in the lint paths."""
        paths = discover_ruff_paths()
        assert "scripts" in paths

    def test_includes_github_skills(self, synthetic_workspace):
        """``.github/skills`` (host-only eval drivers) is in the lint paths."""
        paths = discover_ruff_paths()
        assert ".github/skills" in paths

    def test_includes_library_source_dirs(self, synthetic_workspace):
        """Every library ``src/`` directory appears in the lint paths."""
        paths = discover_ruff_paths()
        assert "libraries/lib_a/src" in paths
        assert "libraries/lib_b/src" in paths

    def test_includes_workbench_source_dirs(self, synthetic_workspace):
        """Workbench ``src/`` directories appear in the lint paths."""
        paths = discover_ruff_paths()
        assert "workbench/tool_x/src" in paths

    def test_includes_tests_when_present(self, synthetic_workspace):
        """``tests/`` directories are included when they exist."""
        paths = discover_ruff_paths()
        assert "libraries/lib_a/tests" in paths
        # lib_b has no tests/ in the synthetic layout
        assert "libraries/lib_b/tests" not in paths


class TestCoverageArgsFor:
    """Tests for coverage_args_for."""

    def test_generates_cov_args(self, synthetic_workspace):
        """Generates --cov arguments for libraries with importable packages."""
        library_dir = synthetic_workspace / "libraries" / "lib_a"
        args = coverage_args_for([library_dir])
        assert "--cov" in args
        assert any("chumicro_lib_a" in argument for argument in args)

    def test_empty_list(self):
        """Empty input produces empty output."""
        assert coverage_args_for([]) == []


class TestResolveNamedPackages:
    """Tests for resolve_named_packages."""

    def test_resolve_by_name(self, synthetic_workspace):
        """Resolves a bare library name to its directory."""
        result = resolve_named_packages(["lib_a"])
        assert len(result) == 1
        assert result[0].name == "lib_a"

    def test_resolve_multiple(self, synthetic_workspace):
        """Resolves multiple names."""
        result = resolve_named_packages(["lib_a", "lib_b"])
        names = {directory.name for directory in result}
        assert names == {"lib_a", "lib_b"}

    def test_unknown_name_returns_empty(self, synthetic_workspace, capsys):
        """Unknown package name returns empty list and prints error."""
        result = resolve_named_packages(["nonexistent"])
        assert result == []
        captured = capsys.readouterr()
        assert "Unknown package: nonexistent" in captured.out


class TestFindPublishablePackages:
    """Tests for find_publishable_packages."""

    def test_versionless_support_package_excluded(
        self, synthetic_workspace,
    ):
        """A support package without a VERSION is held out of the publish
        set (Decision 0111): ``support/helper`` has none, so it is absent
        while every returned path lives under a publishable root."""
        packages = find_publishable_packages()
        assert len(packages) > 0
        assert all(
            package.startswith(("libraries/", "workbench/", "support/"))
            for package in packages
        )
        assert "support/helper" not in packages

    def test_support_package_with_version_included(
        self, synthetic_workspace,
    ):
        """A support package publishes once it carries a VERSION
        (Decision 0111): give ``support/helper`` one and it joins the set."""
        (synthetic_workspace / "support" / "helper" / "VERSION").write_text("0.3.0\n")
        assert "support/helper" in find_publishable_packages()

    def test_every_publishable_package_has_version(
        self, synthetic_workspace,
    ):
        """Every publishable package returned by ``find_publishable_packages``
        has a VERSION file in the synthetic tree — confirms the function
        only enumerates packages that satisfy the Decision-0002 contract."""
        for package in find_publishable_packages():
            version_path = synthetic_workspace / package / "VERSION"
            assert version_path.exists(), f"Missing VERSION: {package}"

    def test_excludes_parked_by_default(self, synthetic_workspace):
        """A parked library drops out of the publish set (Decision 0107)."""
        (synthetic_workspace / "libraries" / "lib_a" / PARKED_MARKER).write_text(
            "parked for testing\n",
        )
        packages = find_publishable_packages()
        assert "libraries/lib_a" not in packages
        # Siblings are unaffected.
        assert "libraries/lib_b" in packages

    def test_include_parked_flag_returns_parked(self, synthetic_workspace):
        """``include_parked=True`` restores parked libraries for dev-time
        consumers (editable install keeps them importable)."""
        (synthetic_workspace / "libraries" / "lib_a" / PARKED_MARKER).write_text(
            "parked for testing\n",
        )
        packages = find_publishable_packages(include_parked=True)
        assert "libraries/lib_a" in packages
        assert "libraries/lib_b" in packages


class TestParkedLibraries:
    """Tests for the parked-library marker helpers (Decision 0107)."""

    def test_is_parked_false_without_marker(self, synthetic_workspace):
        """A library with no marker is not parked."""
        assert is_parked(synthetic_workspace / "libraries" / "lib_a") is False

    def test_is_parked_true_with_marker(self, synthetic_workspace):
        """Presence of the marker file parks the library."""
        library_dir = synthetic_workspace / "libraries" / "lib_a"
        (library_dir / PARKED_MARKER).write_text("why + when\n")
        assert is_parked(library_dir) is True

    def test_marker_directory_does_not_count(self, synthetic_workspace):
        """A directory named PARKED is not a marker — only a file parks."""
        library_dir = synthetic_workspace / "libraries" / "lib_a"
        (library_dir / PARKED_MARKER).mkdir()
        assert is_parked(library_dir) is False

    def test_read_parked_reason_returns_contents(self, synthetic_workspace):
        """The recorded reason is read back, trimmed."""
        library_dir = synthetic_workspace / "libraries" / "lib_a"
        (library_dir / PARKED_MARKER).write_text("  zero adopters; parked 2026-07-05  \n")
        assert read_parked_reason(library_dir) == "zero adopters; parked 2026-07-05"

    def test_read_parked_reason_none_when_unparked(self, synthetic_workspace):
        """An un-parked library has no reason."""
        assert read_parked_reason(synthetic_workspace / "libraries" / "lib_a") is None

    def test_read_parked_reason_none_when_marker_empty(self, synthetic_workspace):
        """An empty marker file yields None rather than an empty string."""
        library_dir = synthetic_workspace / "libraries" / "lib_a"
        (library_dir / PARKED_MARKER).write_text("   \n")
        assert read_parked_reason(library_dir) is None

    def test_parked_library_still_discovered_for_tests(self, synthetic_workspace):
        """Parking excludes from publish, not from test/lint discovery —
        a parked library still appears in discover_library_dirs()."""
        (synthetic_workspace / "libraries" / "lib_a" / PARKED_MARKER).write_text("p\n")
        names = {directory.name for directory in discover_library_dirs()}
        assert "lib_a" in names


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
    """Tests for changed_publishable_packages — file path classification.

    Inputs are synthetic git-diff outputs; the path classification is
    pure string parsing and does not look at on-disk state, so no
    workspace fixture is needed here.
    """

    def test_library_src_change_detected(self, monkeypatch):
        """A change under libraries/<name>/src/ is release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: ["libraries/syn_lib/src/chumicro_syn_lib/core.py"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "syn_lib")}

    def test_library_pyproject_change_detected(self, monkeypatch):
        """A change to libraries/<name>/pyproject.toml is release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: ["libraries/syn_lib/pyproject.toml"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "syn_lib")}

    def test_workbench_src_change_detected(self, monkeypatch):
        """A change under workbench/<name>/src/ is release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: ["workbench/syn_tool/src/chumicro_syn_tool/core.py"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("workbench", "syn_tool")}

    def test_workbench_pyproject_change_detected(self, monkeypatch):
        """A change to workbench/<name>/pyproject.toml is release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: ["workbench/syn_tool/pyproject.toml"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("workbench", "syn_tool")}

    def test_test_change_not_detected(self, monkeypatch):
        """A change under <root>/<name>/tests/ is NOT release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: [
                "libraries/syn_lib/tests/test_a.py",
                "workbench/syn_tool/tests/test_b.py",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == set()

    def test_docs_change_not_detected(self, monkeypatch):
        """A change under <root>/<name>/docs/ is NOT release-relevant."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: ["libraries/syn_lib/docs/guide.md"],
        )
        result = changed_publishable_packages("origin/main")
        assert result == set()

    def test_mixed_roots(self, monkeypatch):
        """Changes across libraries/ and workbench/ are both detected."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: [
                "libraries/syn_lib/src/chumicro_syn_lib/core.py",
                "workbench/syn_tool/src/chumicro_syn_tool/core.py",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("libraries", "syn_lib"), ("workbench", "syn_tool")}

    def test_support_src_change_detected(self, monkeypatch):
        """support/ is publishable (Decision 0111), so a src change there
        is release-relevant; non-package paths are still ignored."""
        monkeypatch.setattr(
            "repo_layout.changed_files",
            lambda _base: [
                "support/syn_helper/src/syn_helper/core.py",
                "scripts/run.py",
                "README.md",
            ],
        )
        result = changed_publishable_packages("origin/main")
        assert result == {("support", "syn_helper")}


class TestReleaseRelevant:
    """Verify the RELEASE_RELEVANT constant."""

    def test_expected_entries(self):
        """RELEASE_RELEVANT contains the expected set."""
        assert RELEASE_RELEVANT == {"src", "pyproject.toml"}


class TestPublishableRoots:
    """Verify the PUBLISHABLE_ROOTS constant."""

    def test_expected_entries(self):
        """PUBLISHABLE_ROOTS covers libraries/, workbench/, and support/."""
        assert PUBLISHABLE_ROOTS == ("libraries", "workbench", "support")


class TestDetectChangedPackages:
    """Tests for detect_changed_packages."""

    def test_infrastructure_change_returns_none(self, monkeypatch):
        """Changes to scripts/ trigger all-packages testing."""
        monkeypatch.setattr(
            "repo_layout.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "scripts/run.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_conftest_change_returns_none(self, monkeypatch):
        """Changes to root conftest.py trigger all-packages testing."""
        monkeypatch.setattr(
            "repo_layout.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": "conftest.py\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_github_change_returns_none(self, monkeypatch):
        """Changes to .github/ trigger all-packages testing."""
        monkeypatch.setattr(
            "repo_layout.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (), {"returncode": 0, "stdout": ".github/workflows/ci.yml\n"},
            )(),
        )
        assert detect_changed_packages() is None

    def test_no_changes_returns_none(self, monkeypatch):
        """No changed files returns None (run everything)."""
        monkeypatch.setattr(
            "repo_layout.subprocess.run",
            lambda *_args, **_kwargs: type("R", (), {"returncode": 0, "stdout": ""})(),
        )
        assert detect_changed_packages() is None

    def test_library_change_detected(self, synthetic_workspace, monkeypatch):
        """Library changes return the affected package directories."""
        monkeypatch.setattr(
            "repo_layout.subprocess.run",
            lambda *_args, **_kwargs: type(
                "R", (),
                {
                    "returncode": 0,
                    "stdout": "libraries/lib_a/src/chumicro_lib_a/core.py\n",
                },
            )(),
        )
        result = detect_changed_packages()
        assert result is not None
        names = [package_dir.name for package_dir in result]
        assert "lib_a" in names

    def test_untracked_only_package_detected(
        self, synthetic_workspace, monkeypatch,
    ):
        """A package whose only changes are untracked new files is detected.

        The three ``git diff`` forms never list untracked files; only the
        added ``ls-files --others`` query sees a brand-new un-added module,
        so without it such a package would escape change detection.
        """
        def fake_run(args, **_kwargs):
            # args is ("git", <subcommand>, ...); the untracked query is
            # the only one returning the new file's path.
            is_ls_others = args[1] == "ls-files" and "--others" in args
            stdout = (
                "libraries/lib_a/src/chumicro_lib_a/new_module.py\n"
                if is_ls_others else ""
            )
            return type("R", (), {"returncode": 0, "stdout": stdout})()

        monkeypatch.setattr("repo_layout.subprocess.run", fake_run)
        result = detect_changed_packages()
        assert result is not None
        assert "lib_a" in [package_dir.name for package_dir in result]

    def test_ls_files_others_included_in_union(self, monkeypatch):
        """detect_changed_packages issues the untracked-files query."""
        seen_subcommands: list[str] = []

        def fake_run(args, **_kwargs):
            # Record the git form: ("git", "diff"/"ls-files", ...).
            seen_subcommands.append(" ".join(args[1:]))
            return type("R", (), {"returncode": 0, "stdout": ""})()

        monkeypatch.setattr("repo_layout.subprocess.run", fake_run)
        detect_changed_packages()
        assert any(
            "ls-files --others --exclude-standard" in subcommand
            for subcommand in seen_subcommands
        )

    def test_git_unavailable_returns_none(self, monkeypatch):
        """When git is not available, returns None."""
        def raise_not_found(*_args, **_kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("repo_layout.subprocess.run", raise_not_found)
        assert detect_changed_packages() is None


class TestResolveScope:
    """Tests for resolve_scope."""

    def test_all_packages(self, synthetic_workspace):
        """``--all`` returns every synthetic package."""
        result = resolve_scope(all_packages=True)
        names = {package_dir.name for package_dir in result}
        assert names == {"lib_a", "lib_b", "tool_x", "helper"}

    def test_specific_libraries(self, synthetic_workspace):
        """``--libraries`` returns only the named packages."""
        result = resolve_scope(libraries="lib_a")
        assert len(result) == 1
        assert result[0].name == "lib_a"

    def test_unknown_library_exits(self, synthetic_workspace):
        """Unknown library name raises ``SystemExit``."""
        with pytest.raises(SystemExit):
            resolve_scope(libraries="nonexistent")


class TestPythonpathEnvironment:
    """Tests for pythonpath_environment."""

    def test_returns_dict(self, synthetic_workspace):
        """Returns a dict with ``PYTHONPATH`` set."""
        environment = pythonpath_environment()
        assert isinstance(environment, dict)
        assert "PYTHONPATH" in environment

    def test_includes_source_roots(self, synthetic_workspace):
        """``PYTHONPATH`` contains every synthetic package's ``src/``."""
        environment = pythonpath_environment()
        pythonpath = environment["PYTHONPATH"]
        for name in ("lib_a", "lib_b", "tool_x", "helper"):
            assert name in pythonpath, (
                f"{name!r} missing from PYTHONPATH={pythonpath!r}"
            )

    def test_preserves_existing_path(self, synthetic_workspace, monkeypatch):
        """Existing ``PYTHONPATH`` entries are preserved."""
        monkeypatch.setenv("PYTHONPATH", "/existing/path")
        environment = pythonpath_environment()
        assert "/existing/path" in environment["PYTHONPATH"]

    def test_includes_path(self, synthetic_workspace):
        """``PATH`` from ``os.environ`` is preserved."""
        environment = pythonpath_environment()
        assert "PATH" in environment


class TestDiscoverLibraryDirs:
    """Tests for discover_library_dirs."""

    def test_returns_only_libraries(self, synthetic_workspace):
        """Returns the library packages and only those."""
        names = {library_dir.name for library_dir in discover_library_dirs()}
        assert names == {"lib_a", "lib_b"}

    def test_all_under_libraries(self, synthetic_workspace):
        """Every returned directory is under ``libraries/``."""
        for library_dir in discover_library_dirs():
            assert library_dir.parent.name == "libraries"

    def test_excludes_support_and_workbench(self, synthetic_workspace):
        """Support and workbench packages are not included."""
        names = {library_dir.name for library_dir in discover_library_dirs()}
        assert "helper" not in names  # support
        assert "tool_x" not in names  # workbench

    def test_subset_of_discover_package_dirs(self, synthetic_workspace):
        """Results are a subset of ``discover_package_dirs``."""
        all_dirs = {str(directory) for directory in discover_package_dirs()}
        library_dirs = {str(directory) for directory in discover_library_dirs()}
        assert library_dirs.issubset(all_dirs)


class TestDiscoverWorkbenchDirs:
    """Tests for discover_workbench_dirs."""

    def test_returns_only_workbench(self, synthetic_workspace):
        """Returns the workbench packages and only those."""
        names = {workbench_dir.name for workbench_dir in discover_workbench_dirs()}
        assert names == {"tool_x"}

    def test_all_under_workbench(self, synthetic_workspace):
        """Every returned directory is under ``workbench/``."""
        for workbench_dir in discover_workbench_dirs():
            assert workbench_dir.parent.name == "workbench"

    def test_excludes_libraries(self, synthetic_workspace):
        """Library packages are not included."""
        names = {workbench_dir.name for workbench_dir in discover_workbench_dirs()}
        library_names = {library_dir.name for library_dir in discover_library_dirs()}
        assert names.isdisjoint(library_names)

    def test_subset_of_discover_package_dirs(self, synthetic_workspace):
        """Results are a subset of ``discover_package_dirs``."""
        all_dirs = {str(directory) for directory in discover_package_dirs()}
        workbench_dirs = {str(directory) for directory in discover_workbench_dirs()}
        assert workbench_dirs.issubset(all_dirs)


class TestReadPyprojectDescription:
    """Tests for read_pyproject_description."""

    def test_reads_from_pyproject(self, tmp_path: Path):
        """Reads the description field from a synthetic pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-synth"\n'
            'description = "A synthetic library for testing."\n',
        )
        description = read_pyproject_description(tmp_path)
        assert description == "A synthetic library for testing."
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

    def test_returns_only_packages_with_mkdocs(self, synthetic_workspace):
        """Returns the synthetic packages that carry an ``mkdocs.yml``.

        Synthetic ``lib_a`` and ``tool_x`` have ``mkdocs.yml``;
        ``lib_b`` and ``helper`` do not — confirms the filter both
        includes and excludes correctly without depending on which
        real packages happen to ship docs.
        """
        names = {doc_dir.name for doc_dir in discover_doc_dirs()}
        assert names == {"lib_a", "tool_x"}

    def test_all_have_mkdocs(self, synthetic_workspace):
        """Every directory returned has an ``mkdocs.yml`` on disk."""
        for doc_dir in discover_doc_dirs():
            assert (doc_dir / "mkdocs.yml").exists()

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


class TestReleaseTags:
    """Tests for release_tags — stable-vs-experimental baseline selection."""

    #: Order git's ``--sort=-v:refname`` emits with no ``versionsort.suffix``
    #: configured: the ``-experimental`` suffix ranks *above* the bare stable
    #: tag of the same version.
    _MIXED_TAGS = (
        "chumicro-timing-v0.10.0-experimental\n"
        "chumicro-timing-v0.10.0\n"
        "chumicro-timing-v0.9.0-experimental\n"
        "chumicro-timing-v0.9.0\n"
        "chumicro-timing-v0.3.0\n"
    )

    def _patch_tags(self, monkeypatch, output):
        import subprocess

        monkeypatch.setattr(
            repo_layout, "run_git",
            lambda *args, **kwargs: subprocess.CompletedProcess(
                args=list(args), returncode=0, stdout=output,
            ),
        )

    def test_default_returns_every_tag_newest_first(self, monkeypatch):
        """Without stable_only, every tag (incl. experimental) is returned."""
        self._patch_tags(monkeypatch, self._MIXED_TAGS)
        tags = repo_layout.release_tags("timing")
        assert tags[0] == "chumicro-timing-v0.10.0-experimental"
        assert "chumicro-timing-v0.9.0-experimental" in tags

    def test_stable_only_drops_experimental_so_stable_wins(self, monkeypatch):
        """stable_only filters pre-release tags; the newest stable is first."""
        self._patch_tags(monkeypatch, self._MIXED_TAGS)
        tags = repo_layout.release_tags("timing", stable_only=True)
        assert tags[0] == "chumicro-timing-v0.10.0"
        assert all("-experimental" not in tag for tag in tags)
        assert tags == [
            "chumicro-timing-v0.10.0",
            "chumicro-timing-v0.9.0",
            "chumicro-timing-v0.3.0",
        ]

    def test_stable_only_with_no_stable_tags_returns_empty(self, monkeypatch):
        """A package with only experimental tags has no stable baseline."""
        self._patch_tags(
            monkeypatch, "chumicro-timing-v0.2.0-experimental\n",
        )
        assert repo_layout.release_tags("timing", stable_only=True) == []

    def test_no_tags_returns_empty(self, monkeypatch):
        """No matching tags → empty list regardless of stable_only."""
        self._patch_tags(monkeypatch, "")
        assert repo_layout.release_tags("timing", stable_only=True) == []


class TestEffectiveDiffBase:
    """Tests for effective_diff_base — the direct-to-main push fallback."""

    #: Git environment overrides so commits work in CI (no global user config).
    _GIT_ENV = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test",
    }

    def _git(self, *arguments: str, cwd: Path) -> None:
        """Run a git command with CI-safe identity."""
        import os
        import subprocess

        merged = {**os.environ, **self._GIT_ENV}
        subprocess.run(
            ["git", *arguments],
            cwd=cwd, capture_output=True, check=True, env=merged,
        )

    def _repo_with_commits(self, tmp_path: Path, monkeypatch, count: int) -> Path:
        """Init a repo at tmp_path with *count* empty commits; pin ROOT to it."""
        self._git("init", cwd=tmp_path)
        for index in range(count):
            self._git("commit", "--allow-empty", "-m", f"c{index}", cwd=tmp_path)
        monkeypatch.setattr(repo_layout, "ROOT", tmp_path)
        return tmp_path

    def test_base_at_head_falls_back_to_parent(self, tmp_path, monkeypatch, capsys):
        """origin/main == HEAD (the direct-to-main push shape) → HEAD^."""
        repo = self._repo_with_commits(tmp_path, monkeypatch, count=2)
        self._git("branch", "pushed-main", cwd=repo)

        assert effective_diff_base("pushed-main") == "HEAD^"
        assert "diffing against HEAD^" in capsys.readouterr().out

    def test_base_behind_head_is_unchanged(self, tmp_path, monkeypatch):
        """A base ref that differs from HEAD is used as-is."""
        repo = self._repo_with_commits(tmp_path, monkeypatch, count=1)
        self._git("branch", "old-main", cwd=repo)
        self._git("commit", "--allow-empty", "-m", "newer", cwd=repo)

        assert effective_diff_base("old-main") == "old-main"

    def test_root_commit_keeps_base(self, tmp_path, monkeypatch):
        """HEAD with no parent (root commit) keeps the original base."""
        repo = self._repo_with_commits(tmp_path, monkeypatch, count=1)
        self._git("branch", "pushed-main", cwd=repo)

        assert effective_diff_base("pushed-main") == "pushed-main"

    def test_unresolvable_base_is_unchanged(self, tmp_path, monkeypatch):
        """A ref that doesn't resolve is returned untouched."""
        self._repo_with_commits(tmp_path, monkeypatch, count=2)

        assert effective_diff_base("origin/nonexistent") == "origin/nonexistent"
