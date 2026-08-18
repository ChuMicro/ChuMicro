"""Tests for bundle.py — bundle staging, manifest generation, and utilities."""

import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest
from bundle_manager import (
    CP_MPY_FOLDER,
    DEVICE_RUNTIMES,
    EXPERIMENTAL_BUNDLE_REPO,
    MPY_FORMAT_FOLDER,
    STABLE_BUNDLE_REPO,
    _bundle_data_files,
    _collect_library_metadata,
    _data_files_from,
    _derive_bundle_id,
    _experimental_dependency,
    _find_bundle_modules,
    _project_dependencies_span,
    _read_chumicro_dependencies,
    build_bundle,
    build_circup_zips,
    finalize_bundle_tag,
    generate_bundle_readme,
    next_date_tag,
    patch_experimental,
    pin_bundle_deps,
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
        """Discovers deployable .py files under the package."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "core.py").write_text("# core")

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

    def test_cpython_marker_drops_testing_py_from_every_bundle(
        self, tmp_path: Path,
    ):
        """testing.py declares ``__chumicro_runtimes__ = ("cpython",)`` so
        it's filtered out of every bundle (CP-mpy, MP-mpy, source) by the
        marker mechanism.  Only the PyPI sdist / wheel ships testing.py."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "testing.py").write_text(
            '__chumicro_runtimes__ = ("cpython",)\n',
        )

        for target in ("circuitpython", "micropython", DEVICE_RUNTIMES):
            _, _, files = _find_bundle_modules(tmp_path, target_runtime=target)
            filenames = {file.name for file in files}
            assert filenames == {"__init__.py"}, (
                f"testing.py leaked into target_runtime={target!r}"
            )

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

    def test_source_bundle_keeps_device_marked_files_drops_cpython_only(
        self, tmp_path: Path,
    ):
        """The source bundle uses ``target_runtime=DEVICE_RUNTIMES`` so any
        CP- or MP-marked file rides along (it'll be useful on at least one
        device runtime), but ``("cpython",)``-marked files drop out — they
        belong only in the PyPI sdist / wheel."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "cp_only.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (package_dir / "mp_only.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )
        (package_dir / "cpython_only.py").write_text(
            '__chumicro_runtimes__ = ("cpython",)\n',
        )

        _, _, files = _find_bundle_modules(
            tmp_path, target_runtime=DEVICE_RUNTIMES,
        )
        filenames = {file.name for file in files}
        assert filenames == {"__init__.py", "cp_only.py", "mp_only.py"}

    def test_data_files_inherit_their_modules_runtime_marker(
        self, tmp_path: Path,
    ):
        """An MP-only module's declared data file is dropped from the
        CircuitPython selection with it — the module-level runtime
        filter runs before ``_bundle_data_files`` reads declarations,
        so the 16 KB CA-bundle .der class never rides a CP channel.
        Pins the bundle side of the cross-channel selection contract
        (the deploy walker pins its own)."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "bundle.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n'
            "__chumicro_data_files__ = ('roots.der',)\n",
        )
        (package_dir / "roots.der").write_bytes(b"DER")

        _, _, cp_files = _find_bundle_modules(
            tmp_path, target_runtime="circuitpython",
        )
        assert _bundle_data_files(cp_files) == []

        _, _, mp_files = _find_bundle_modules(
            tmp_path, target_runtime="micropython",
        )
        assert [f.name for f in _bundle_data_files(mp_files)] == ["roots.der"]

    def test_target_runtime_none_is_unfiltered(self, tmp_path: Path):
        """``target_runtime=None`` (legacy default) ships every file
        regardless of marker — preserved so external callers that haven't
        opted into a target still get the prior behavior."""
        package_dir = tmp_path / "src" / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("")
        (package_dir / "cpython_only.py").write_text(
            '__chumicro_runtimes__ = ("cpython",)\n',
        )

        _, _, files = _find_bundle_modules(tmp_path, target_runtime=None)
        filenames = {file.name for file in files}
        assert filenames == {"__init__.py", "cpython_only.py"}

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


class TestDataFilesExtraction:
    """Tests for _data_files_from and _bundle_data_files."""

    def test_reads_tuple_marker(self, tmp_path: Path):
        """A tuple ``__chumicro_data_files__`` yields its string entries in order."""
        module = tmp_path / "mod.py"
        module.write_text('__chumicro_data_files__ = ("a.der", "b.bin")\n')
        assert _data_files_from(module) == ["a.der", "b.bin"]

    def test_reads_list_marker(self, tmp_path: Path):
        """A list literal marker is read the same as a tuple."""
        module = tmp_path / "mod.py"
        module.write_text("__chumicro_data_files__ = ['a.der']\n")
        assert _data_files_from(module) == ["a.der"]

    def test_absent_marker_returns_empty(self, tmp_path: Path):
        """A module without the marker yields no data files."""
        module = tmp_path / "mod.py"
        module.write_text("x = 1\n")
        assert _data_files_from(module) == []

    def test_syntax_error_returns_empty(self, tmp_path: Path):
        """An unparseable module yields no data files rather than raising."""
        module = tmp_path / "mod.py"
        module.write_text("def (:\n")
        assert _data_files_from(module) == []

    def test_bundle_data_files_resolves_existing_siblings(self, tmp_path: Path):
        """Only siblings that exist on disk are returned; missing names drop."""
        module = tmp_path / "mod.py"
        module.write_text('__chumicro_data_files__ = ("present.der", "missing.der")\n')
        (tmp_path / "present.der").write_bytes(b"\x00")
        assert _bundle_data_files([module]) == [tmp_path / "present.der"]

    def test_bundle_data_files_dedupes(self, tmp_path: Path):
        """Two modules naming the same sibling file yield it once."""
        (tmp_path / "shared.der").write_bytes(b"\x00")
        module_a = tmp_path / "a.py"
        module_a.write_text('__chumicro_data_files__ = ("shared.der",)\n')
        module_b = tmp_path / "b.py"
        module_b.write_text('__chumicro_data_files__ = ("shared.der",)\n')
        assert _bundle_data_files([module_a, module_b]) == [tmp_path / "shared.der"]


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


#: Git environment overrides so commits work in CI (no global user config).
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test",
}


def _git(*arguments: str, cwd: Path) -> None:
    """Run a git command with CI-safe identity."""
    import subprocess

    merged = {**os.environ, **_GIT_ENV}
    subprocess.run(
        ["git", *arguments],
        cwd=cwd, capture_output=True, check=True, env=merged,
    )


class TestNextDateTag:
    """Tests for next_date_tag."""

    def _git(self, *arguments: str, cwd: Path) -> None:
        """Run a git command with CI-safe identity."""
        _git(*arguments, cwd=cwd)

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

    def test_reuse_if_clean_returns_highest_head_date_tag(self, tmp_path: Path):
        """A clean checkout whose HEAD carries date tags reuses the highest
        one (numeric compare — .10 outranks .9) instead of minting a new tag."""
        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)
        for tag_name in ["20260101", "20260101.9", "20260101.10", "v1.0.0"]:
            self._git("tag", tag_name, cwd=tmp_path)

        assert next_date_tag(tmp_path, reuse_if_clean=True) == "20260101.10"

    def test_reuse_if_clean_dirty_tree_mints_next_tag(self, tmp_path: Path):
        """A dirty working tree falls through to the existing next-tag
        behavior even though HEAD carries a date tag."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)
        self._git("tag", today, cwd=tmp_path)
        (tmp_path / "untracked.txt").write_text("dirty\n")

        assert next_date_tag(tmp_path, reuse_if_clean=True) == f"{today}.1"

    def test_reuse_if_clean_without_head_date_tag_mints_next_tag(self, tmp_path: Path):
        """A clean tree whose HEAD carries no date-shaped tag mints a new tag."""
        self._git("init", cwd=tmp_path)
        self._git("commit", "--allow-empty", "-m", "init", cwd=tmp_path)
        self._git("tag", "v1.0.0", cwd=tmp_path)

        tag = next_date_tag(tmp_path, reuse_if_clean=True)
        assert len(tag) == 8
        assert tag.isdigit()


def _write_manifest(
    manifest_path: Path,
    deps: list[list[str]] | None,
    version: str = "1.0.0",
) -> None:
    """Write a package.json in build_bundle's exact serialization."""
    package = manifest_path.parent.name
    manifest: dict = {
        "urls": [[f"{package}/x.py", f"github:ChuMicro/ChuMicro-Bundle/{package}/x.py"]],
        "version": version,
    }
    if deps:
        manifest["deps"] = deps
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)
        manifest_file.write("\n")


def _manifest_deps(manifest_path: Path) -> list[list[str]]:
    """Read back a manifest's deps list."""
    return json.loads(manifest_path.read_text()).get("deps", [])


class TestPinBundleDeps:
    """Tests for pin_bundle_deps."""

    def test_scan_rewrites_only_placeholder_entries(self, tmp_path: Path):
        """A scan pins HEAD-placeholder deps and leaves real pins alone."""
        manifest = tmp_path / "chumicro_runner" / "package.json"
        _write_manifest(manifest, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "HEAD"],
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_config", "20260101"],
        ])

        rewritten = pin_bundle_deps(tmp_path, "20260711")

        assert rewritten == [manifest]
        assert _manifest_deps(manifest) == [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "20260711"],
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_config", "20260101"],
        ]

    def test_scan_skips_manifests_without_deps(self, tmp_path: Path):
        """Dependency-free manifests are not rewritten (or returned)."""
        manifest = tmp_path / "chumicro_timing" / "package.json"
        _write_manifest(manifest, None)
        before = manifest.read_text()

        assert pin_bundle_deps(tmp_path, "20260711") == []
        assert manifest.read_text() == before

    def test_explicit_manifests_repin_all_entries(self, tmp_path: Path):
        """An explicit manifest list rewrites every dep entry to the tag."""
        staged = tmp_path / "chumicro_runner" / "package.json"
        untouched = tmp_path / "chumicro_mqtt" / "package.json"
        _write_manifest(staged, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "20260101"],
        ])
        _write_manifest(untouched, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "20260101"],
        ])

        rewritten = pin_bundle_deps(tmp_path, "20260711", manifests=[staged])

        assert rewritten == [staged]
        assert _manifest_deps(staged)[0][1] == "20260711"
        assert _manifest_deps(untouched)[0][1] == "20260101"

    def test_rewrite_preserves_build_bundle_serialization(self, tmp_path: Path):
        """A pinned manifest stays byte-identical to build_bundle's output
        for the same content (indent-2 JSON plus trailing newline)."""
        manifest = tmp_path / "chumicro_runner" / "package.json"
        _write_manifest(manifest, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "HEAD"],
        ])
        expected = tmp_path / "expected" / "chumicro_runner" / "package.json"
        _write_manifest(expected, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "20260711"],
        ])

        pin_bundle_deps(tmp_path / "chumicro_runner", "20260711")

        assert manifest.read_bytes() == expected.read_bytes()


class TestFinalizeBundleTag:
    """Tests for finalize_bundle_tag."""

    def test_first_push_mints_tag_and_pins_placeholders(self, tmp_path: Path):
        """With no date tag on HEAD, the minted tag lands in the manifests."""
        _git("init", cwd=tmp_path)
        _git("commit", "--allow-empty", "-m", "seed", cwd=tmp_path)
        manifest = tmp_path / "chumicro_runner" / "package.json"
        _write_manifest(manifest, [
            ["github:ChuMicro/ChuMicro-Bundle/chumicro_timing", "HEAD"],
        ])

        tag = finalize_bundle_tag(tmp_path, reuse_if_clean=True)

        assert len(tag) == 8 and tag.isdigit()
        assert _manifest_deps(manifest)[0][1] == tag

    def test_no_change_rerun_reuses_tag_and_stays_clean(self, tmp_path: Path):
        """Re-staging identical content over a pushed bundle reuses HEAD's
        tag and leaves the tree byte-identical (the re-run no-op path)."""
        _git("init", cwd=tmp_path)
        manifest = tmp_path / "chumicro_runner" / "package.json"
        dependency_reference = "github:ChuMicro/ChuMicro-Bundle/chumicro_timing"
        _write_manifest(manifest, [[dependency_reference, "20260101"]])
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "release", cwd=tmp_path)
        _git("tag", "20260101", cwd=tmp_path)

        # Simulate the overlay of a re-run: same content, placeholder pin.
        _write_manifest(manifest, [[dependency_reference, "HEAD"]])

        tag = finalize_bundle_tag(tmp_path, reuse_if_clean=True)

        assert tag == "20260101"
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        )
        assert status.stdout.strip() == ""

    def test_real_change_mints_new_tag_and_repins(self, tmp_path: Path):
        """A genuine release mints the next tag, pins the staged manifest to
        it, and leaves a prior push's manifest pinned to its own snapshot."""
        _git("init", cwd=tmp_path)
        staged = tmp_path / "chumicro_runner" / "package.json"
        old = tmp_path / "chumicro_mqtt" / "package.json"
        dependency_reference = "github:ChuMicro/ChuMicro-Bundle/chumicro_timing"
        _write_manifest(staged, [[dependency_reference, "20260101"]], version="1.0.0")
        _write_manifest(old, [[dependency_reference, "20251231"]])
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-m", "release", cwd=tmp_path)
        _git("tag", "20260101", cwd=tmp_path)

        # Overlay of a new runner release: bumped version, placeholder pin.
        _write_manifest(staged, [[dependency_reference, "HEAD"]], version="1.1.0")

        tag = finalize_bundle_tag(tmp_path, reuse_if_clean=True)

        assert tag != "20260101"
        assert _manifest_deps(staged)[0][1] == tag
        assert _manifest_deps(old)[0][1] == "20251231"


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
            'Documentation = "https://chumicro.com/ChuMicro/timing/stable/"\n'
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

    def test_hyphenated_name_from_project_table(self, tmp_path: Path):
        """B1: the name comes from [project].name, not the directory.

        ``libraries/http_server/`` declares ``chumicro-http-server`` — a
        directory-derived ``chumicro-http_server`` would miss it and exit.
        """
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-http-server"\n'
        )
        library_dir = tmp_path / "http_server"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-http-server-experimental"' in patched

    def test_missing_name_exits(self, tmp_path: Path):
        """A pyproject with no [project].name exits (B1 guard preserved)."""
        library_dir = tmp_path / "broken"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')

        with pytest.raises(SystemExit):
            patch_experimental(library_dir)

    def test_rewrites_chumicro_deps_with_and_without_specifiers(self, tmp_path: Path):
        """B2: chumicro deps gain -experimental; specifiers are preserved."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-http-server"\n'
            'dependencies = [\n'
            '    "chumicro-config",\n'
            '    "chumicro-deploy>=0.1.0",\n'
            ']\n'
        )
        library_dir = tmp_path / "http_server"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert '"chumicro-config-experimental"' in patched
        assert '"chumicro-deploy-experimental>=0.1.0"' in patched
        # No un-suffixed intra-chumicro dep survives.
        assert '"chumicro-config"' not in patched
        assert '"chumicro-deploy>=0.1.0"' not in patched

    def test_leaves_non_chumicro_deps_untouched(self, tmp_path: Path):
        """B2: third-party deps are not rewritten."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-workspace"\n'
            'dependencies = [\n'
            '    "chumicro-deploy",\n'
            '    "msgpack>=1.0",\n'
            '    "ruamel.yaml>=0.18",\n'
            ']\n'
        )
        library_dir = tmp_path / "workspace"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert '"chumicro-deploy-experimental"' in patched
        assert '"msgpack>=1.0"' in patched
        assert '"ruamel.yaml>=0.18"' in patched
        assert "msgpack-experimental" not in patched
        assert "ruamel.yaml-experimental" not in patched

    def test_rewrites_optional_dependencies(self, tmp_path: Path):
        """Intra-chumicro [test] extras are rewritten too, so
        `pip install chumicro-<lib>-experimental[test]` resolves against the
        experimental test tooling.  Non-chumicro extras (pytest) are left."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-http-server"\n'
            'dependencies = [\n'
            '    "chumicro-config",\n'
            ']\n'
            '\n'
            '[project.optional-dependencies]\n'
            'test = [\n'
            '    "pytest",\n'
            '    "chumicro-config",\n'
            '    "chumicro-test-harness",\n'
            ']\n'
        )
        library_dir = tmp_path / "http_server"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        # Runtime dep + the test-extra copy of it are both rewritten.
        assert patched.count('"chumicro-config-experimental"') == 2
        assert patched.count('"chumicro-config"') == 0
        assert '"chumicro-test-harness-experimental"' in patched
        # Non-chumicro extras stay put.
        assert '"pytest"' in patched
        assert "experimental-experimental" not in patched

    def test_package_with_no_deps(self, tmp_path: Path):
        """A package with no dependencies patches name/URLs and no more."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-timing"\n'
            'dependencies = []\n'
        )
        library_dir = tmp_path / "timing"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-timing-experimental"' in patched
        assert "-experimental>" not in patched

    def test_already_patched_is_noop(self, tmp_path: Path, capsys):
        """A second run leaves the file byte-identical — no
        '-experimental-experimental' name and no new PyPI project."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-http-server-experimental"\n'
            'dependencies = [\n'
            '    "chumicro-config-experimental",\n'
            '    "chumicro-deploy-experimental>=0.1.0",\n'
            ']\n'
            '\n'
            '[project.urls]\n'
            'Bundle = "https://github.com/ChuMicro/ChuMicro-Bundle-Experimental"\n'
        )
        library_dir = tmp_path / "http_server"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        assert (library_dir / "pyproject.toml").read_text() == pyproject_content
        assert "already patched" in capsys.readouterr().out

    def test_already_suffixed_dep_not_resuffixed(self, tmp_path: Path):
        """A dep already on the experimental channel keeps a single suffix
        while the rest of the pyproject still patches."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-http-server"\n'
            'dependencies = [\n'
            '    "chumicro-config-experimental",\n'
            '    "chumicro-deploy>=0.1.0",\n'
            ']\n'
        )
        library_dir = tmp_path / "http_server"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-http-server-experimental"' in patched
        assert '"chumicro-config-experimental"' in patched
        assert '"chumicro-deploy-experimental>=0.1.0"' in patched
        assert "experimental-experimental" not in patched

    def test_single_line_dependencies_array(self, tmp_path: Path):
        """A one-line runtime array and the [test] extra are each rewritten
        exactly once — the runtime span finder does not spill into the
        optional-dependencies table, and the optional rewrite handles it."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-workspace"\n'
            'dependencies = ["chumicro-msgpack>=0.2.0"]\n'
            '\n'
            '[project.optional-dependencies]\n'
            'test = [\n'
            '    "chumicro-msgpack>=0.2.0",\n'
            ']\n'
        )
        library_dir = tmp_path / "workspace"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        # Both copies (runtime + test extra) rewritten exactly once each.
        assert patched.count('"chumicro-msgpack-experimental>=0.2.0"') == 2
        assert patched.count('"chumicro-msgpack>=0.2.0"') == 0
        assert "experimental-experimental" not in patched

    def test_single_line_dependencies_at_end_of_file(self, tmp_path: Path):
        """A one-line array with no later bare ']' line patches instead of
        exiting (the span finder used to return None here)."""
        pyproject_content = (
            '[project]\n'
            'name = "chumicro-workspace"\n'
            'dependencies = ["chumicro-msgpack>=0.2.0"]\n'
        )
        library_dir = tmp_path / "workspace"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(pyproject_content)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'dependencies = ["chumicro-msgpack-experimental>=0.2.0"]' in patched


class TestPatchExperimentalReadme:
    """patch_experimental also patches the library README (the PyPI
    long-description) so an experimental project page never shows stable
    install commands.  Rewrites stay scoped to install-command lines;
    labeled cross-channel links in prose keep their targets."""

    _PYPROJECT = (
        '[project]\n'
        'name = "chumicro-timing"\n'
        '\n'
        '[project.urls]\n'
        'Bundle = "https://github.com/ChuMicro/ChuMicro-Bundle"\n'
        'Documentation = "https://chumicro.com/ChuMicro/timing/stable/"\n'
    )

    _README = (
        "# chumicro-timing\n"
        "\n"
        "```bash\n"
        "# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)\n"
        "circup install chumicro_timing\n"
        "mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing\n"
        "pip install chumicro-timing\n"
        "```\n"
        "\n"
        "[Stable docs](https://chumicro.com/ChuMicro/timing/stable/)\n"
        "[Experimental bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental"
        "/tree/main/chumicro_timing)\n"
        "Everything in chumicro-timing works on CPython too.\n"
    )

    def _make_library(self, tmp_path: Path) -> Path:
        library_dir = tmp_path / "timing"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(self._PYPROJECT)
        (library_dir / "README.md").write_text(self._README)
        return library_dir

    def test_pip_install_line_rewritten(self, tmp_path: Path):
        """The pip install line gains -experimental; a prose mention of the
        stable name outside a pip install line stays untouched."""
        library_dir = self._make_library(tmp_path)

        patch_experimental(library_dir)

        patched = (library_dir / "README.md").read_text()
        assert "pip install chumicro-timing-experimental\n" in patched
        assert "Everything in chumicro-timing works on CPython too.\n" in patched

    def test_bundle_references_rewritten(self, tmp_path: Path):
        """ChuMicro-Bundle references move to the experimental bundle repo;
        an already-experimental reference is not double-suffixed."""
        library_dir = self._make_library(tmp_path)

        patch_experimental(library_dir)

        patched = (library_dir / "README.md").read_text()
        assert "circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental" in patched
        assert "github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing" in patched
        assert "Bundle-Experimental-Experimental" not in patched

    def test_stable_rewrites_scoped_to_install_lines(self, tmp_path: Path):
        """/stable/ switches to /experimental/ on install-command lines only.

        The labeled footer link ("Stable docs") keeps its target — a
        rewritten target under an unchanged label would lie.
        """
        library_dir = self._make_library(tmp_path)
        readme = library_dir / "README.md"
        readme.write_text(
            readme.read_text()
            + "pip install chumicro-timing  "
            + "# docs: https://chumicro.com/ChuMicro/timing/stable/\n"
        )

        patch_experimental(library_dir)

        patched = readme.read_text()
        assert "[Stable docs](https://chumicro.com/ChuMicro/timing/stable/)" in patched
        assert (
            "pip install chumicro-timing-experimental  "
            "# docs: https://chumicro.com/ChuMicro/timing/experimental/" in patched
        )

    def test_second_run_leaves_readme_byte_identical(self, tmp_path: Path):
        """A second run hits the pyproject idempotency guard and leaves the
        README byte-identical to the first run's output."""
        library_dir = self._make_library(tmp_path)

        patch_experimental(library_dir)
        first_run_readme = (library_dir / "README.md").read_text()

        patch_experimental(library_dir)

        assert (library_dir / "README.md").read_text() == first_run_readme

    def test_package_without_readme_works(self, tmp_path: Path):
        """A library without a README.md still patches its pyproject."""
        library_dir = tmp_path / "timing"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(self._PYPROJECT)

        patch_experimental(library_dir)

        patched = (library_dir / "pyproject.toml").read_text()
        assert 'name = "chumicro-timing-experimental"' in patched


class TestExperimentalDependency:
    """Tests for _experimental_dependency."""

    def test_appends_suffix_preserving_specifier(self):
        """The suffix lands on the name; the specifier is untouched."""
        result = _experimental_dependency("chumicro-deploy>=0.1.0")
        assert result == "chumicro-deploy-experimental>=0.1.0"

    def test_bare_name(self):
        """A specifier-less entry gains just the suffix."""
        assert _experimental_dependency("chumicro-config") == "chumicro-config-experimental"

    def test_already_suffixed_returns_unchanged(self):
        """A dep already on the experimental channel is not re-suffixed."""
        dependency = "chumicro-deploy-experimental>=0.1.0"
        assert _experimental_dependency(dependency) == dependency


class TestProjectDependenciesSpan:
    """Tests for _project_dependencies_span."""

    def test_multi_line_array_spans_to_bare_bracket(self):
        """The span runs from the opening line through the bare ']' line."""
        content = (
            'dependencies = [\n'
            '    "chumicro-config",\n'
            ']\n'
            '\n'
            '[project.optional-dependencies]\n'
        )
        span = _project_dependencies_span(content)

        assert span is not None
        start, end = span
        assert content[start:end] == 'dependencies = [\n    "chumicro-config",\n]\n'

    def test_single_line_array_closes_on_opening_line(self):
        """A ']' on the opening line closes the array — the span must not
        extend into [project.optional-dependencies]."""
        content = (
            'dependencies = ["chumicro-msgpack>=0.2.0"]\n'
            '\n'
            '[project.optional-dependencies]\n'
            'test = [\n'
            '    "chumicro-msgpack>=0.2.0",\n'
            ']\n'
        )
        span = _project_dependencies_span(content)

        assert span is not None
        start, end = span
        assert content[start:end] == 'dependencies = ["chumicro-msgpack>=0.2.0"]\n'

    def test_absent_array_returns_none(self):
        """No dependencies array yields None."""
        assert _project_dependencies_span('[project]\nname = "chumicro-timing"\n') is None


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
        _write_bundle_manifest(package_dir, ["__init__.py", "core.py"])

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
        _write_bundle_manifest(package_dir, ["__init__.py"])

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
        (package_dir / "core.py").write_text("# core")
        _write_bundle_manifest(package_dir, ["__init__.py", "core.py"])

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
        _write_bundle_manifest(package_dir, ["__init__.py"])

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

    def test_source_zip_includes_declared_data_file(self, tmp_path: Path):
        """The source zip carries a __chumicro_data_files__ sibling next to its module."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "_ca_bundle.py").write_text(
            '__chumicro_data_files__ = ("_ca_bundle.der",)\n',
        )
        (package_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")
        _write_bundle_manifest(
            package_dir, ["__init__.py", "_ca_bundle.py"],
            data_relpaths=["_ca_bundle.der"],
        )

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        import zipfile

        source_zip_path = output_dir / "chumicro-bundle-py-20260101.zip"
        with zipfile.ZipFile(source_zip_path) as source_zip:
            names = source_zip.namelist()
        assert any(name.endswith("_ca_bundle.der") for name in names)
        assert any(name.endswith("_ca_bundle.py") for name in names)

    def test_bytecode_zip_includes_staged_data_file(self, tmp_path: Path):
        """The bytecode zip carries raw data files staged beside the .mpy modules."""
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"

        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")
        _write_bundle_manifest(
            package_dir, ["__init__.py"], data_relpaths=["_ca_bundle.der"],
        )

        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")
        (cp_mpy_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        import zipfile

        bytecode_zip_path = output_dir / "chumicro-bundle-10.x-mpy-20260101.zip"
        with zipfile.ZipFile(bytecode_zip_path) as bytecode_zip:
            names = bytecode_zip.namelist()
        assert any(name.endswith("_ca_bundle.der") for name in names)
        assert any(name.endswith("__init__.mpy") for name in names)

    def test_no_packages_returns_empty(self, tmp_path: Path):
        """Empty bundle directory returns empty list."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        output_dir = tmp_path / "output"

        zips = build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        assert zips == []


def _write_bundle_manifest(
    package_dir: Path, py_relpaths: list[str], data_relpaths: list[str] = (),
) -> None:
    """Write a mip-style package.json listing *current* package files.

    Mirrors what ``build_bundle`` emits: each ``urls`` entry is
    ``[target, source]`` with target ``"<package_name>/<relpath>"``.
    """
    package_name = package_dir.name
    urls = [
        [f"{package_name}/{relpath}", f"github:org/repo/{package_name}/{relpath}"]
        for relpath in [*py_relpaths, *data_relpaths]
    ]
    (package_dir / "package.json").write_text(
        json.dumps({"urls": urls, "version": "0.1.0"}) + "\n",
    )


class TestBuildCircupZipsManifestProtection:
    """S1: circup zips ship only files this build's package.json declares.

    The bundle repo is a fresh clone the release overlays new files onto
    with ``cp -r`` (no delete), so a module removed or renamed upstream
    lingers on disk.  build_circup_zips must not glob those stale files
    into the zip — it ships what the regenerated manifest lists.
    """

    def _zip_names(self, path: Path) -> list[str]:
        import zipfile

        with zipfile.ZipFile(path) as archive:
            return archive.namelist()

    def test_source_zip_excludes_stale_py_not_in_manifest(self, tmp_path: Path):
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"
        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "core.py").write_text("# core")
        # A prior release shipped removed.py; the overlay left it on disk,
        # but this build's manifest does not list it.
        (package_dir / "removed.py").write_text("# stale, removed upstream")
        _write_bundle_manifest(package_dir, ["__init__.py", "core.py"])

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        names = self._zip_names(output_dir / "chumicro-bundle-py-20260101.zip")
        assert any(name.endswith("/core.py") for name in names)
        assert any(name.endswith("/__init__.py") for name in names)
        assert not any(name.endswith("/removed.py") for name in names)

    def test_bytecode_zip_excludes_stale_mpy_not_in_manifest(self, tmp_path: Path):
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"
        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "core.py").write_text("# core")
        _write_bundle_manifest(package_dir, ["__init__.py", "core.py"])

        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")
        (cp_mpy_dir / "core.mpy").write_bytes(b"C\x06mpy")
        # Stale bytecode from a removed module.
        (cp_mpy_dir / "removed.mpy").write_bytes(b"C\x06mpy")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        names = self._zip_names(output_dir / "chumicro-bundle-10.x-mpy-20260101.zip")
        assert any(name.endswith("/core.mpy") for name in names)
        assert any(name.endswith("/__init__.mpy") for name in names)
        assert not any(name.endswith("/removed.mpy") for name in names)

    def test_manifest_data_file_ships_in_both_zips(self, tmp_path: Path):
        bundle_dir = tmp_path / "bundle"
        output_dir = tmp_path / "output"
        package_dir = bundle_dir / "chumicro_example"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init")
        (package_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")
        _write_bundle_manifest(
            package_dir, ["__init__.py"], data_relpaths=["_ca_bundle.der"],
        )

        cp_mpy_dir = bundle_dir / CP_MPY_FOLDER / "chumicro_example"
        cp_mpy_dir.mkdir(parents=True)
        (cp_mpy_dir / "__init__.mpy").write_bytes(b"C\x06mpy")
        (cp_mpy_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")

        build_circup_zips(
            bundle_dir, output_dir, "ChuMicro-Bundle", date_tag="20260101",
        )
        source_names = self._zip_names(output_dir / "chumicro-bundle-py-20260101.zip")
        bytecode_names = self._zip_names(
            output_dir / "chumicro-bundle-10.x-mpy-20260101.zip",
        )
        assert any(name.endswith("/_ca_bundle.der") for name in source_names)
        assert any(name.endswith("/_ca_bundle.der") for name in bytecode_names)


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

    def test_skips_parked_library(self, tmp_path: Path):
        """A parked library is left out of the bundle README metadata
        (Decision 0107): it never enters the bundle, so it must not be
        advertised there."""
        libraries_dir = tmp_path / "libraries"
        _make_test_library(libraries_dir, name="mqtt")
        _make_test_library(libraries_dir, name="logging")
        (libraries_dir / "logging" / "PARKED").write_text("zero adopters\n")

        metadata = _collect_library_metadata(tmp_path)

        names = {entry["name"] for entry in metadata}
        assert names == {"mqtt"}


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


def _make_data_file_library(tmp_path: Path) -> Path:
    """A library whose MicroPython-only module declares a sibling data file.

    Mirrors chumicro_sockets: ``_ca_bundle.py`` is marked micropython-only
    and names ``_ca_bundle.der`` via ``__chumicro_data_files__``.
    """
    library_dir = _make_test_library(tmp_path, name="datalib")
    package_dir = library_dir / "src" / "chumicro_datalib"
    (package_dir / "_ca_bundle.py").write_text(
        '__chumicro_runtimes__ = ("micropython",)\n'
        '__chumicro_data_files__ = ("_ca_bundle.der",)\n',
    )
    (package_dir / "_ca_bundle.der").write_bytes(b"\x30\x82fake-der")
    return library_dir


class TestBundleDataFiles:
    """build_bundle stages and manifests __chumicro_data_files__ siblings."""

    def test_source_bundle_stages_and_lists_data_file(self, tmp_path: Path) -> None:
        """The source bundle copies the .der and lists it in package.json urls."""
        library_dir = _make_data_file_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        build_bundle(library_dir, "0.1.0", staging_dir)

        package_dir = staging_dir / "chumicro_datalib"
        assert (package_dir / "_ca_bundle.der").is_file()
        manifest = json.loads((package_dir / "package.json").read_text())
        assert any(entry[0].endswith("_ca_bundle.der") for entry in manifest["urls"])

    def test_mp_mpy_stages_raw_der_and_lists_it(self, tmp_path: Path) -> None:
        """The mpy6 bundle ships the .der raw (uncompiled) and lists it in urls."""
        library_dir = _make_data_file_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")
        build_bundle(
            library_dir, "0.1.0", staging_dir, mp_mpy_cross=str(fake_mpy),
        )

        mpy_dir = staging_dir / MPY_FORMAT_FOLDER / "chumicro_datalib"
        # The .der ships raw (its own bytes, uncompiled); the module beside
        # it compiles to _ca_bundle.mpy as usual.
        assert (mpy_dir / "_ca_bundle.der").read_bytes() == b"\x30\x82fake-der"
        manifest = json.loads((mpy_dir / "package.json").read_text())
        assert any(target.endswith("_ca_bundle.der") for target, _ in manifest["urls"])

    def test_cp_mpy_excludes_micropython_only_data_file(self, tmp_path: Path) -> None:
        """A micropython-only module and its .der stay out of the CircuitPython bundle."""
        library_dir = _make_data_file_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")
        build_bundle(
            library_dir, "0.1.0", staging_dir, cp_mpy_cross=str(fake_mpy),
        )

        cp_mpy_dir = staging_dir / CP_MPY_FOLDER / "chumicro_datalib"
        assert not (cp_mpy_dir / "_ca_bundle.der").exists()
        assert not (cp_mpy_dir / "_ca_bundle.mpy").exists()


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


class TestMpyDependencyReferenceFollowsItsFolder:
    """The mpy dep reference resolves inside the folder being staged.

    Decision 0112 puts a folder per live mpy ABI side by side in the one
    bundle repo.  A manifest staged into a newer folder whose deps still
    pointed at the older one would have mip assemble a mixed-format tree on
    the board, so the folder is threaded in rather than read from the module
    constant at the point of use.
    """

    def test_defaults_to_the_current_format_folder(self):
        from bundle_manager import _dependency_to_mpy_mip_reference

        reference = _dependency_to_mpy_mip_reference(
            "chumicro-timing>=0.1", "ChuMicro-Bundle",
        )
        assert reference == (
            f"github:ChuMicro/ChuMicro-Bundle/{MPY_FORMAT_FOLDER}/chumicro_timing"
        )

    def test_uses_the_folder_it_is_given(self):
        from bundle_manager import _dependency_to_mpy_mip_reference

        reference = _dependency_to_mpy_mip_reference(
            "chumicro-timing>=0.1", "ChuMicro-Bundle", "mpy7",
        )
        assert reference == (
            "github:ChuMicro/ChuMicro-Bundle/mpy7/chumicro_timing"
        )
        assert MPY_FORMAT_FOLDER not in reference

    def test_staged_manifest_deps_match_the_staged_folder(
        self, tmp_path: Path,
    ) -> None:
        """Every dep in a staged manifest points at that manifest's folder.

        Guards the whole path rather than the helper alone: staging names the
        folder once, and every URL and dependency below it agrees.
        """
        library_dir = _make_test_library(tmp_path)
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-fakelib"\n'
            'version = "0.1.0"\n'
            'dependencies = ["chumicro-timing>=0.1"]\n',
        )
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")
        build_bundle(
            library_dir, "0.1.0", staging_dir, mp_mpy_cross=str(fake_mpy),
        )

        manifest_path = (
            staging_dir / MPY_FORMAT_FOLDER / "chumicro_fakelib" / "package.json"
        )
        manifest = json.loads(manifest_path.read_text())
        deps = manifest.get("deps", [])
        assert deps, "expected the staged mpy manifest to carry a dependency"
        for reference, _pin in deps:
            assert f"/{MPY_FORMAT_FOLDER}/" in reference
        for _target, source in manifest["urls"]:
            assert f"/{MPY_FORMAT_FOLDER}/" in source


class TestCircupRequirementsMetadata:
    """The circup zips carry the dependency metadata circup reads.

    circup resolves a library's dependencies from
    ``requirements/<library>/requirements.txt`` inside the bundle.  Ours
    shipped only ``lib/``, so `circup install chumicro_mqtt` installed mqtt
    alone and the board raised ImportError on first import.  mip carries
    deps in package.json and was the only install path with coverage, which
    is why the whole CircuitPython side shipped dependency-less.
    """

    def _bundle_with_dependency(self, tmp_path: Path) -> Path:
        library_dir = _make_test_library(tmp_path)
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-fakelib"\n'
            'version = "0.1.0"\n'
            'dependencies = ["chumicro-timing>=0.1", "chumicro-config"]\n',
        )
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        fake_mpy = _make_fake_mpy_cross(tmp_path / "tools")
        build_bundle(
            library_dir, "0.1.0", staging_dir, cp_mpy_cross=str(fake_mpy),
        )
        output_dir = tmp_path / "zips"
        build_circup_zips(
            staging_dir, output_dir, "ChuMicro-Bundle", date_tag="20260808",
        )
        return output_dir

    def test_source_zip_carries_requirements(self, tmp_path: Path) -> None:
        output_dir = self._bundle_with_dependency(tmp_path)
        zip_path = output_dir / "chumicro-bundle-py-20260808.zip"
        with zipfile.ZipFile(zip_path) as archive:
            body = archive.read(
                "chumicro-bundle-py-20260808/requirements"
                "/chumicro_fakelib/requirements.txt",
            ).decode()
        assert body.split() == ["chumicro_config", "chumicro_timing"]

    def test_bytecode_zip_carries_requirements(self, tmp_path: Path) -> None:
        """A user who registered only the mpy bundle resolves deps too."""
        output_dir = self._bundle_with_dependency(tmp_path)
        zip_path = output_dir / "chumicro-bundle-10.x-mpy-20260808.zip"
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
        assert any("/requirements/chumicro_fakelib/" in name for name in names)

    def test_names_are_import_names_not_pypi_names(self, tmp_path: Path) -> None:
        """circup matches against lib/ directory names, which are underscored.

        A hyphenated ``chumicro-config`` line parses to a name circup finds
        no module for, and it is skipped in silence.
        """
        output_dir = self._bundle_with_dependency(tmp_path)
        with zipfile.ZipFile(output_dir / "chumicro-bundle-py-20260808.zip") as archive:
            body = archive.read(
                "chumicro-bundle-py-20260808/requirements"
                "/chumicro_fakelib/requirements.txt",
            ).decode()
        assert "-" not in body
        for line in body.split():
            assert line.startswith("chumicro_")

    def test_dependency_free_package_gets_no_requirements_file(
        self, tmp_path: Path,
    ) -> None:
        """Nothing to declare means no file, matching circup's absent lookup."""
        library_dir = _make_test_library(tmp_path)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        build_bundle(library_dir, "0.1.0", staging_dir)
        output_dir = tmp_path / "zips"
        build_circup_zips(
            staging_dir, output_dir, "ChuMicro-Bundle", date_tag="20260808",
        )
        with zipfile.ZipFile(output_dir / "chumicro-bundle-py-20260808.zip") as archive:
            names = archive.namelist()
        assert not [name for name in names if "requirements" in name]

    def test_requirements_agree_with_the_mip_manifest(self, tmp_path: Path) -> None:
        """Both install paths project the same deps, so they cannot drift."""
        library_dir = _make_test_library(tmp_path)
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
        mip_deps = {
            reference.rsplit("/", 1)[-1] for reference, _pin in manifest["deps"]
        }
        output_dir = tmp_path / "zips"
        build_circup_zips(
            staging_dir, output_dir, "ChuMicro-Bundle", date_tag="20260808",
        )
        with zipfile.ZipFile(output_dir / "chumicro-bundle-py-20260808.zip") as archive:
            body = archive.read(
                "chumicro-bundle-py-20260808/requirements"
                "/chumicro_fakelib/requirements.txt",
            ).decode()
        assert set(body.split()) == mip_deps
