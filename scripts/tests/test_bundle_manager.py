"""Tests for bundle.py — bundle staging, manifest generation, and utilities."""

from pathlib import Path

from bundle_manager import (
    CP_MPY_FOLDER,
    EXPERIMENTAL_BUNDLE_REPO,
    STABLE_BUNDLE_REPO,
    _collect_library_metadata,
    _derive_bundle_id,
    _find_bundle_modules,
    _read_chumicro_dependencies,
    build_circup_zips,
    generate_bundle_readme,
    next_date_tag,
    patch_experimental,
)


class TestDeriveBundleId:
    """Tests for _derive_bundle_id."""

    def test_stable_bundle(self):
        """Stable bundle name converts correctly."""
        assert _derive_bundle_id("ChuMicro-Bundle") == "chumicro-bundle"

    def test_experimental_bundle(self):
        """Experimental bundle name converts correctly."""
        assert _derive_bundle_id("ChuMicro-Bundle-Experimental") == "chumicro-bundle-experimental"

    def test_underscores_become_hyphens(self):
        """Underscores are replaced with hyphens."""
        assert _derive_bundle_id("Some_Repo_Name") == "some-repo-name"


class TestFindBundleModules:
    """Tests for _find_bundle_modules."""

    def test_finds_python_files(self, tmp_path: Path):
        """Discovers .py files under the package directory."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "core.py").write_text("# core")
        (package_dir / "testing.py").write_text("# testing")

        name, found_dir, files = _find_bundle_modules(tmp_path)
        assert name == "chumicro_example"
        assert found_dir == package_dir
        assert len(files) == 3
        filenames = {file.name for file in files}
        assert filenames == {"__init__.py", "core.py", "testing.py"}

    def test_skips_pycache(self, tmp_path: Path):
        """__pycache__ files are excluded."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        cache_dir = package_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "core.cpython-311.pyc").write_text("")

        _, _, files = _find_bundle_modules(tmp_path)
        assert len(files) == 1  # only __init__.py


class TestReadChuMicroDependencies:
    """Tests for _read_chumicro_dependencies."""

    def test_no_dependencies(self, tmp_path: Path):
        """Library with no chumicro dependencies returns empty list."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-test"\n'
        )
        assert _read_chumicro_dependencies(tmp_path) == []

    def test_chumicro_dependencies(self, tmp_path: Path):
        """Library with chumicro dependencies returns them."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-test"\n'
            'dependencies = ["chumicro-timing>=0.1", "requests"]\n'
        )
        result = _read_chumicro_dependencies(tmp_path)
        assert result == ["chumicro-timing>=0.1"]

    def test_multiple_chumicro_dependencies(self, tmp_path: Path):
        """Multiple chumicro dependencies are all returned."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-test"\n'
            'dependencies = ["chumicro-timing>=0.1", "chumicro-runner>=0.2"]\n'
        )
        result = _read_chumicro_dependencies(tmp_path)
        assert len(result) == 2


class TestNextDateTag:
    """Tests for next_date_tag."""

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

    def test_no_existing_tags(self, tmp_path: Path, monkeypatch):
        """No existing tags returns today's date."""
        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)

        tag = next_date_tag(tmp_path)
        # Should be a YYYYMMDD format string.
        assert len(tag) == 8
        assert tag.isdigit()

    def test_one_existing_tag(self, tmp_path: Path):
        """One existing tag for today returns today.1."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)
        self._git("tag", today, cwd=tmp_path)

        tag = next_date_tag(tmp_path)
        assert tag == f"{today}.1"

    def test_multiple_existing_tags(self, tmp_path: Path):
        """Multiple existing tags for today returns next suffix."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)
        for tag_name in [today, f"{today}.1", f"{today}.2"]:
            self._git("tag", tag_name, cwd=tmp_path)

        tag = next_date_tag(tmp_path)
        assert tag == f"{today}.3"

        tag = next_date_tag(tmp_path)
        assert tag == f"{today}.3"


class TestPatchExperimental:
    """Tests for patch_experimental."""

    def test_patches_pyproject(self, tmp_path: Path):
        """Patches the package name, bundle URL, and docs URL."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-timing"\n'
            '\n'
            '[project.urls]\n'
            'Bundle = "https://github.com/ChuMicro/ChuMicro-Bundle"\n'
            'Documentation = "https://chumicro.github.io/ChuMicro/timing/stable/"\n'
        )
        library_dir = tmp_path / "timing"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-timing-experimental"' in patched
        assert "ChuMicro-Bundle-Experimental" in patched
        assert '/experimental/"' in patched
        assert '/stable/"' not in patched


class TestBuildCircupZips:
    """Tests for build_circup_zips."""

    def test_creates_zip_files(self, tmp_path: Path):
        """Creates source and bytecode zip bundles."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        # Root package: .py source only.
        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "core.py").write_text("# core")

        # circuitpython-10.x-mpy/: CircuitPython .mpy bytecode.
        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")
        (cp_mpy_dir / "core.mpy").write_bytes(b"C\x06mpy")

        zips = build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        assert len(zips) == 2
        assert all(zip_path.exists() for zip_path in zips)

        # Verify filenames follow the circup naming convention.
        zip_names = {zip_path.name for zip_path in zips}
        assert "chumicro-bundle-py-20260101.zip" in zip_names
        assert "chumicro-bundle-10.x-mpy-20260101.zip" in zip_names

    def test_source_zip_contains_only_py(self, tmp_path: Path):
        """Source zip contains only .py files, not .mpy."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")

        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        import zipfile

        source_zip_path = output_dir / "chumicro-bundle-py-20260101.zip"
        with zipfile.ZipFile(source_zip_path) as source_zip:
            names = source_zip.namelist()
            assert all(name.endswith(".py") for name in names)
            assert any("__init__.py" in name for name in names)

    def test_bytecode_zip_pulls_from_circuitpython_mpy(self, tmp_path: Path):
        """Bytecode zip contains .mpy files from circuitpython-10.x-mpy/ directory."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")

        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")
        (cp_mpy_dir / "core.mpy").write_bytes(b"C\x06mpy")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        import zipfile

        bytecode_zip_path = output_dir / "chumicro-bundle-10.x-mpy-20260101.zip"
        with zipfile.ZipFile(bytecode_zip_path) as bytecode_zip:
            names = bytecode_zip.namelist()
            assert all(name.endswith(".mpy") for name in names)
            assert len(names) == 2

    def test_ignores_micropython_mpy6_folder(self, tmp_path: Path):
        """Bytecode zip does not include files from mpy6/ (MicroPython) folder."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")

        # Only MicroPython mpy6/ present — no circuitpython-10.x-mpy/ folder.
        mp_mpy_dir = bundle_dir / "mpy6" / "chumicro_example"
        mp_mpy_dir.mkdir(parents=True)
        (mp_mpy_dir / "__init__.mpy").write_bytes(b"M\x06mpy")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        import zipfile

        bytecode_zip_path = output_dir / "chumicro-bundle-10.x-mpy-20260101.zip"
        with zipfile.ZipFile(bytecode_zip_path) as bytecode_zip:
            # Should be empty — no CircuitPython .mpy files staged.
            assert bytecode_zip.namelist() == []

    def test_no_packages_returns_empty(self, tmp_path: Path):
        """Empty bundle directory returns empty list."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        output_dir = tmp_path / "output"

        zips = build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        assert zips == []


class TestCollectLibraryMetadata:
    """Tests for _collect_library_metadata (uses real workspace)."""

    def test_finds_libraries(self):
        """Discovers metadata for existing libraries."""
        from workspace import ROOT

        metadata = _collect_library_metadata(ROOT)
        assert len(metadata) > 0
        names = {entry["name"] for entry in metadata}
        assert "timing" in names

    def test_metadata_has_expected_keys(self):
        """Each metadata entry has the expected keys."""
        from workspace import ROOT

        metadata = _collect_library_metadata(ROOT)
        for entry in metadata:
            assert "name" in entry
            assert "package_name" in entry
            assert "version" in entry
            assert "description" in entry


class TestGenerateBundleReadme:
    """Tests for generate_bundle_readme."""

    def test_stable_readme(self):
        """Stable README contains expected content."""
        from workspace import ROOT

        readme = generate_bundle_readme(ROOT)
        assert STABLE_BUNDLE_REPO in readme
        assert "circup bundle-add" in readme
        assert "mip install" in readme
        assert "pip install" in readme

    def test_experimental_readme(self):
        """Experimental README contains warning banner."""
        from workspace import ROOT

        readme = generate_bundle_readme(ROOT, experimental=True)
        assert EXPERIMENTAL_BUNDLE_REPO in readme
        assert "Pre-release" in readme


class TestBundleRepoConstants:
    """Tests for bundle repo name constants."""

    def test_stable_repo_name(self):
        """Stable bundle repo has expected name."""
        assert STABLE_BUNDLE_REPO == "ChuMicro-Bundle"

    def test_experimental_repo_name(self):
        """Experimental bundle repo has expected name."""
        assert EXPERIMENTAL_BUNDLE_REPO == "ChuMicro-Bundle-Experimental"
