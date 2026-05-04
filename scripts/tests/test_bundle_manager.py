"""Tests for bundle.py — bundle staging, manifest generation, and utilities."""

import json
import os
import stat
from pathlib import Path

from bundle_manager import (
    CP_MPY_FOLDER,
    EXPERIMENTAL_BUNDLE_REPO,
    MPY_FORMAT_FOLDER,
    STABLE_BUNDLE_REPO,
    _collect_library_metadata,
    _derive_bundle_id,
    _find_bundle_modules,
    _read_chumicro_dependencies,
    build_bundle,
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
        """Discovers deployable .py files; host-only testing.py is excluded."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "core.py").write_text("# core")
        (package_dir / "testing.py").write_text("# testing")

        name, found_dir, files = _find_bundle_modules(tmp_path)
        assert name == "chumicro_example"
        assert found_dir == package_dir
        filenames = {file.name for file in files}
        assert filenames == {"__init__.py", "core.py"}

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

    def test_skips_host_only_testing_module(self, tmp_path: Path):
        """testing.py is a CPython-only host fake; it must not ship to devices."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "testing.py").write_text("# host fake")

        _, _, files = _find_bundle_modules(tmp_path)
        filenames = {file.name for file in files}
        assert "testing.py" not in filenames
        assert filenames == {"__init__.py"}

    def test_filters_by_runtime_marker_for_circuitpython(self, tmp_path: Path):
        """Decision 0037: __chumicro_runtimes__ filters per-runtime bundles."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        adapters = package_dir / "_adapters"
        adapters.mkdir()
        (adapters / "__init__.py").write_text("")
        (adapters / "base.py").write_text("# universal")
        (adapters / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (adapters / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )
        (adapters / "cpython.py").write_text(
            '__chumicro_runtimes__ = ("cpython",)\n',
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime="circuitpython")
        filenames = {file.relative_to(package_dir).as_posix() for file in files}
        # CP-only and universal files ship; MP and CPython markers are filtered out.
        assert filenames == {
            "__init__.py",
            "_adapters/__init__.py",
            "_adapters/base.py",
            "_adapters/cp.py",
        }

    def test_filters_by_runtime_marker_for_micropython(self, tmp_path: Path):
        """Decision 0037: MP bundle excludes CP and CPython files."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        adapters = package_dir / "_adapters"
        adapters.mkdir()
        (adapters / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (adapters / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime="micropython")
        filenames = {file.relative_to(package_dir).as_posix() for file in files}
        assert filenames == {"__init__.py", "_adapters/mp.py"}

    def test_no_marker_means_universal(self, tmp_path: Path):
        """A file without __chumicro_runtimes__ ships to every bundle."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# no marker — universal")
        (package_dir / "core.py").write_text("# no marker — universal")

        for runtime in ("circuitpython", "micropython", None):
            _, _, files = _find_bundle_modules(tmp_path, target_runtime=runtime)
            filenames = {file.name for file in files}
            assert filenames == {"__init__.py", "core.py"}, (
                f"unmarked files should ship to bundle target_runtime={runtime!r}"
            )

    def test_source_bundle_ignores_runtime_markers(self, tmp_path: Path):
        """target_runtime=None ships every non-host-only file regardless of marker."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "cp_only.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (package_dir / "mp_only.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime=None)
        filenames = {file.name for file in files}
        # Source bundle is universal — all marked files come along.
        assert filenames == {"__init__.py", "cp_only.py", "mp_only.py"}

    def test_micropython_submarker_folds_into_micropython(self, tmp_path: Path):
        """Sub-runtime markers (micropython_esp32, micropython_rp2) match 'micropython'."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "esp32.py").write_text(
            '__chumicro_runtimes__ = ("micropython_esp32",)\n',
        )
        (package_dir / "rp2.py").write_text(
            '__chumicro_runtimes__ = ("micropython_rp2",)\n',
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime="micropython")
        filenames = {file.name for file in files}
        assert filenames == {"__init__.py", "esp32.py", "rp2.py"}

        # And CP bundle excludes both.
        _, _, cp_files = _find_bundle_modules(tmp_path, target_runtime="circuitpython")
        cp_filenames = {file.name for file in cp_files}
        assert cp_filenames == {"__init__.py"}

    def test_marker_does_not_require_module_execution(self, tmp_path: Path):
        """Decision 0037: marker is read via AST, not exec — runtime imports may fail."""
        # The cp.py adapter does ``import wifi`` at top level, which fails on
        # CPython.  Verify the bundle pipeline can still classify it.
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "cp.py").write_text(
            '"""CP adapter."""\n'
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            "import this_module_does_not_exist_anywhere\n",
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime="circuitpython")
        filenames = {file.name for file in files}
        assert "cp.py" in filenames

        # And confirm the same file is excluded from MP bundle.
        _, _, mp_files = _find_bundle_modules(tmp_path, target_runtime="micropython")
        mp_filenames = {file.name for file in mp_files}
        assert "cp.py" not in mp_filenames


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
        from repo_layout import ROOT

        metadata = _collect_library_metadata(ROOT)
        assert len(metadata) > 0
        names = {entry["name"] for entry in metadata}
        assert "timing" in names

    def test_metadata_has_expected_keys(self):
        """Each metadata entry has the expected keys."""
        from repo_layout import ROOT

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
        from repo_layout import ROOT

        readme = generate_bundle_readme(ROOT)
        assert STABLE_BUNDLE_REPO in readme
        assert "circup bundle-add" in readme
        assert "mip install" in readme
        assert "pip install" in readme

    def test_experimental_readme(self):
        """Experimental README contains warning banner."""
        from repo_layout import ROOT

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


def _make_fake_mpy_cross(directory: Path) -> Path:
    """Create a fake mpy-cross executable that just writes a stub .mpy file.

    Args:
        directory: Where to write the fake binary.

    Returns:
        Path to the executable.
    """
    directory.mkdir(parents=True, exist_ok=True)
    fake = directory / "fake_mpy_cross.py"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        # Expect: -o <output> <source>
        "output = args[args.index('-o') + 1]\n"
        "source = args[-1]\n"
        "with open(source, 'rb') as src, open(output, 'wb') as dst:\n"
        "    # Magic byte 'M' for MicroPython, 'C' for CircuitPython — fake\n"
        "    dst.write(b'M\\x06\\x00\\x1f' + src.read())\n",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _make_test_library(tmp_path: Path, name: str = "fakelib") -> Path:
    """Create a fake library directory with the minimum bundle-able shape."""
    library_dir = tmp_path / name
    package_dir = library_dir / "src" / f"chumicro_{name}"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        f"\"\"\"Fake {name} package for testing.\"\"\"\n"
        f"VERSION = '0.1.0'\n",
    )
    (package_dir / "core.py").write_text("def hello():\n    return 'world'\n")
    (library_dir / "VERSION").write_text("0.1.0\n")
    (library_dir / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "chumicro-{name}"\n'
        'version = "0.1.0"\n'
        'dependencies = []\n',
    )
    (library_dir / "README.md").write_text(f"# chumicro-{name}\n\nFake.\n")
    return library_dir


class TestBuildBundle:
    """Tests for build_bundle staging behavior."""

    def test_stages_py_source_and_manifest(self, tmp_path: Path) -> None:
        """build_bundle copies .py files and writes a package.json manifest."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        build_bundle(library_dir, "0.1.0", staging_dir)

        package_dir = staging_dir / "chumicro_fakelib"
        assert (package_dir / "__init__.py").is_file()
        assert (package_dir / "core.py").is_file()
        assert (package_dir / "package.json").is_file()
        assert (package_dir / "README.md").is_file()

        manifest = json.loads((package_dir / "package.json").read_text())
        assert manifest["version"] == "0.1.0"
        assert "urls" in manifest
        # Each url is [target, github source].
        assert all(len(entry) == 2 for entry in manifest["urls"])
        assert any("__init__.py" in entry[0] for entry in manifest["urls"])
        assert any("core.py" in entry[0] for entry in manifest["urls"])

    def test_stable_uses_stable_bundle_repo_in_urls(self, tmp_path: Path) -> None:
        """Stable bundle URLs reference the stable bundle repo."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        build_bundle(library_dir, "0.1.0", staging_dir, experimental=False)

        manifest = json.loads(
            (staging_dir / "chumicro_fakelib" / "package.json").read_text(),
        )
        for _, source in manifest["urls"]:
            assert STABLE_BUNDLE_REPO in source

    def test_experimental_uses_experimental_bundle_repo_in_urls(
        self, tmp_path: Path,
    ) -> None:
        """Experimental bundle URLs reference the experimental bundle repo."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        build_bundle(library_dir, "0.1.0", staging_dir, experimental=True)

        manifest = json.loads(
            (staging_dir / "chumicro_fakelib" / "package.json").read_text(),
        )
        for _, source in manifest["urls"]:
            assert EXPERIMENTAL_BUNDLE_REPO in source

    def test_dependencies_emit_deps_in_manifest(self, tmp_path: Path) -> None:
        """A library with chumicro deps gets a `deps` array in package.json."""
        library_dir = _make_test_library(tmp_path)
        # Rewrite pyproject to add a dep.
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-fakelib"\n'
            'version = "0.1.0"\n'
            'dependencies = ["chumicro-timing>=0.1"]\n',
        )
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        build_bundle(library_dir, "0.1.0", staging_dir)

        manifest = json.loads(
            (staging_dir / "chumicro_fakelib" / "package.json").read_text(),
        )
        assert "deps" in manifest
        # Each dep entry is [github reference, ref].
        assert any(
            "chumicro_timing" in dep[0] for dep in manifest["deps"]
        )

    def test_cp_mpy_compilation_creates_circuitpython_folder(
        self, tmp_path: Path,
    ) -> None:
        """When cp_mpy_cross is provided, .mpy files land in circuitpython-10.x-mpy/."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")

        build_bundle(
            library_dir, "0.1.0", staging_dir,
            cp_mpy_cross=str(fake_mpy),
        )

        cp_mpy_dir = staging_dir / CP_MPY_FOLDER / "chumicro_fakelib"
        assert cp_mpy_dir.is_dir()
        assert (cp_mpy_dir / "__init__.mpy").is_file()
        assert (cp_mpy_dir / "core.mpy").is_file()
        # No package.json in the CircuitPython folder (circup uses zip naming).
        assert not (cp_mpy_dir / "package.json").exists()

    def test_mp_mpy_compilation_creates_mpy_folder_with_manifest(
        self, tmp_path: Path,
    ) -> None:
        """When mp_mpy_cross is provided, .mpy files + manifest land in mpy6/."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")

        build_bundle(
            library_dir, "0.1.0", staging_dir,
            mp_mpy_cross=str(fake_mpy),
        )

        mpy_dir = staging_dir / MPY_FORMAT_FOLDER / "chumicro_fakelib"
        assert mpy_dir.is_dir()
        assert (mpy_dir / "__init__.mpy").is_file()
        assert (mpy_dir / "core.mpy").is_file()
        # mpy6 folder has its own package.json (mip needs it).
        manifest = json.loads((mpy_dir / "package.json").read_text())
        assert manifest["version"] == "0.1.0"
        for target, _ in manifest["urls"]:
            assert target.endswith(".mpy")

    def test_both_runtimes_produce_separate_artifacts(self, tmp_path: Path) -> None:
        """Providing both mpy-cross binaries produces both folder layouts."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")

        build_bundle(
            library_dir, "0.1.0", staging_dir,
            cp_mpy_cross=str(fake_mpy),
            mp_mpy_cross=str(fake_mpy),
        )

        assert (staging_dir / CP_MPY_FOLDER / "chumicro_fakelib").is_dir()
        assert (staging_dir / MPY_FORMAT_FOLDER / "chumicro_fakelib").is_dir()

    def test_no_importable_package_exits(self, tmp_path: Path) -> None:
        """A library with src/ but no chumicro_* package directory exits."""
        library_dir = tmp_path / "empty"
        (library_dir / "src").mkdir(parents=True)
        # No package subdirectory under src/.
        (library_dir / "VERSION").write_text("0.1.0\n")
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-empty"\n'
            'version = "0.1.0"\n'
            'dependencies = []\n',
        )

        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        try:
            build_bundle(library_dir, "0.1.0", staging_dir)
        except SystemExit as exit_signal:
            assert "No importable package" in str(exit_signal)
        else:  # pragma: no cover - test should never reach here
            raise AssertionError("expected SystemExit for empty package")
