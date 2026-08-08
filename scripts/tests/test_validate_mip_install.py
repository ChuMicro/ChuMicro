"""Tests for validate_mip_install.py — mip install validation helpers."""

from pathlib import Path

import validate_mip_install
from validate_mip_install import (
    _intra_workspace_deps,
    _resolve_library_names,
    _write_import_script,
    _write_install_script,
)


class TestWriteInstallScript:
    """Tests for _write_install_script."""

    def test_writes_script_file(self, tmp_path: Path):
        """Creates a Python script file at the target path."""
        target = tmp_path / "install.py"
        install_dir = tmp_path / "lib"
        result = _write_install_script(
            target, "github:ChuMicro/Bundle/chumicro_timing", install_dir,
        )
        assert result == target
        assert target.exists()

    def test_script_contains_mip_import(self, tmp_path: Path):
        """Script imports mip."""
        target = tmp_path / "install.py"
        _write_install_script(
            target, "github:ChuMicro/Bundle/chumicro_timing", tmp_path / "lib",
        )
        content = target.read_text()
        assert "import mip" in content

    def test_script_contains_package_url(self, tmp_path: Path):
        """Script contains the package URL."""
        target = tmp_path / "install.py"
        package_url = "github:ChuMicro/Bundle/chumicro_timing"
        _write_install_script(target, package_url, tmp_path / "lib")
        content = target.read_text()
        assert package_url in content

    def test_script_contains_install_call(self, tmp_path: Path):
        """Script calls mip.install with target directory."""
        target = tmp_path / "install.py"
        install_dir = tmp_path / "lib"
        _write_install_script(
            target, "github:ChuMicro/Bundle/chumicro_timing", install_dir,
        )
        content = target.read_text()
        assert "mip.install(" in content
        assert str(install_dir) in content


class TestWriteImportScript:
    """Tests for _write_import_script."""

    def test_writes_script_file(self, tmp_path: Path):
        """Creates a Python script file at the target path."""
        target = tmp_path / "import_test.py"
        result = _write_import_script(target, "chumicro_timing")
        assert result == target
        assert target.exists()

    def test_script_contains_import_statement(self, tmp_path: Path):
        """Script imports the specified package."""
        target = tmp_path / "import_test.py"
        _write_import_script(target, "chumicro_timing")
        content = target.read_text()
        assert "import chumicro_timing" in content

    def test_script_prints_confirmation(self, tmp_path: Path):
        """Script prints confirmation on successful import."""
        target = tmp_path / "import_test.py"
        _write_import_script(target, "chumicro_timing")
        content = target.read_text()
        assert 'print("import chumicro_timing: OK")' in content


class TestResolveLibraryNames:
    """Tests for _resolve_library_names."""

    def test_parses_comma_separated(self):
        """Parses comma-separated library names."""
        result = _resolve_library_names("timing,runner,compat")
        assert result == ["timing", "runner", "compat"]

    def test_strips_whitespace(self):
        """Strips whitespace from library names."""
        result = _resolve_library_names(" timing , runner ")
        assert result == ["timing", "runner"]

    def test_filters_empty_strings(self):
        """Filters out empty strings from trailing commas."""
        result = _resolve_library_names("timing,,runner,")
        assert result == ["timing", "runner"]

    def test_single_library(self):
        """Single library name returns single-element list."""
        result = _resolve_library_names("timing")
        assert result == ["timing"]

    def test_none_discovers_from_workspace(self, monkeypatch):
        """None argument triggers workspace auto-discovery."""
        # Mock discover_library_dirs to return controlled test data.
        mock_dirs = [
            Path("/workspace/libraries/timing"),
            Path("/workspace/libraries/runner"),
        ]
        monkeypatch.setattr(
            "validate_mip_install.discover_library_dirs",
            lambda: mock_dirs,
        )
        result = _resolve_library_names(None)
        assert set(result) == {"timing", "runner"}

    def test_autodiscovery_excludes_parked(self, monkeypatch):
        """Parked libraries (Decision 0107) drop out of auto-discovery —
        they never enter the bundle, so there's nothing to validate."""
        mock_dirs = [
            Path("/workspace/libraries/timing"),
            Path("/workspace/libraries/logging"),
        ]
        monkeypatch.setattr(
            "validate_mip_install.discover_library_dirs",
            lambda: mock_dirs,
        )
        monkeypatch.setattr(
            "validate_mip_install.is_parked",
            lambda library_dir: library_dir.name == "logging",
        )
        result = _resolve_library_names(None)
        assert result == ["timing"]

    def test_empty_string_triggers_autodiscovery(self, monkeypatch):
        """Empty string triggers workspace auto-discovery (same as None)."""
        # Empty string parses to [], which is falsy, triggering auto-discovery.
        mock_dirs = [
            Path("/workspace/libraries/timing"),
        ]
        monkeypatch.setattr(
            "validate_mip_install.discover_library_dirs",
            lambda: mock_dirs,
        )
        result = _resolve_library_names("")
        assert result == ["timing"]


class TestIntraWorkspaceDeps:
    """Tests for _intra_workspace_deps — pyproject dependency parsing."""

    def test_returns_empty_for_missing_pyproject(self, tmp_path: Path, monkeypatch):
        """A library with no pyproject.toml returns no deps."""
        monkeypatch.setattr(validate_mip_install, "ROOT", tmp_path)
        assert _intra_workspace_deps("nonexistent") == []

    def test_returns_empty_for_no_deps(self, tmp_path: Path, monkeypatch):
        """A library with no project.dependencies returns no deps."""
        library_dir = tmp_path / "libraries" / "lonely"
        library_dir.mkdir(parents=True)
        (library_dir / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-lonely"\nversion = "0.1.0"\n',
        )
        monkeypatch.setattr(validate_mip_install, "ROOT", tmp_path)
        assert _intra_workspace_deps("lonely") == []

    def test_extracts_chumicro_deps_only(self, tmp_path: Path, monkeypatch):
        """Only chumicro-* deps are returned; third-party deps are skipped."""
        library_dir = tmp_path / "libraries" / "consumer"
        library_dir.mkdir(parents=True)
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-consumer"\n'
            'version = "0.1.0"\n'
            'dependencies = [\n'
            '  "chumicro-timing>=0.1",\n'
            '  "chumicro-runner>=0.1.5",\n'
            '  "requests>=2.0",\n'
            "]\n",
        )
        monkeypatch.setattr(validate_mip_install, "ROOT", tmp_path)
        assert _intra_workspace_deps("consumer") == ["timing", "runner"]

    def test_strips_version_specifiers(self, tmp_path: Path, monkeypatch):
        """Version specifiers, env markers, and extras are all stripped."""
        library_dir = tmp_path / "libraries" / "consumer"
        library_dir.mkdir(parents=True)
        (library_dir / "pyproject.toml").write_text(
            "[project]\n"
            'name = "chumicro-consumer"\n'
            'version = "0.1.0"\n'
            'dependencies = [\n'
            '  "chumicro-timing>=0.1,<0.2",\n'
            '  "chumicro-runner==1.0",\n'
            '  "chumicro-msgpack[extra]",\n'
            '  "chumicro-compat;python_version<\'3.11\'",\n'
            "]\n",
        )
        monkeypatch.setattr(validate_mip_install, "ROOT", tmp_path)
        assert _intra_workspace_deps("consumer") == [
            "timing",
            "runner",
            "msgpack",
            "compat",
        ]


class TestBundleLayout:
    """Tests for the shared bundle_layout constants."""

    def test_constants_match_expected_values(self):
        """The mpy folder constants are the expected current values."""
        from bundle_layout import (
            CP_MPY_FOLDER,
            EXPERIMENTAL_BUNDLE_REPO,
            MPY_FORMAT_FOLDER,
            STABLE_BUNDLE_REPO,
        )

        assert MPY_FORMAT_FOLDER == "mpy6"
        assert CP_MPY_FOLDER == "circuitpython-10.x-mpy"
        assert STABLE_BUNDLE_REPO == "ChuMicro-Bundle"
        assert EXPERIMENTAL_BUNDLE_REPO == "ChuMicro-Bundle-Experimental"

    def test_validate_mip_uses_bundle_layout(self):
        """The validator reads its formats from the shared layout module.

        It consumes the ``mpy_format_folders()`` tuple rather than the single
        ``MPY_FORMAT_FOLDER`` constant the producer stages into, so a second
        live ABI folder is validated without touching the validator.  Both
        still resolve to the same source of truth.
        """
        from bundle_layout import MPY_FORMAT_FOLDER as canonical
        from bundle_layout import mpy_format_folders
        from bundle_manager import MPY_FORMAT_FOLDER as via_bundle_manager
        from validate_mip_install import (
            mpy_format_folders as via_validator,
        )

        assert canonical == via_bundle_manager
        assert via_validator is mpy_format_folders
        assert canonical in via_validator()

    def test_folder_helpers_return_tuples(self):
        """mpy_format_folders/cp_mpy_folders return single-element tuples today."""
        from bundle_layout import cp_mpy_folders, mpy_format_folders

        assert mpy_format_folders() == ("mpy6",)
        assert cp_mpy_folders() == ("circuitpython-10.x-mpy",)

    def test_validator_covers_every_live_mpy_format(self, monkeypatch):
        """Adding an ABI folder adds validations without a validator edit.

        This is the property the layout module promises.  With the constant
        inlined the second format silently went unvalidated; the loop makes
        the count follow the tuple.
        """
        import bundle_layout
        import validate_mip_install as validator

        monkeypatch.setattr(
            validator, "mpy_format_folders", lambda: ("mpy6", "mpy7"),
        )
        assert len(validator.mpy_format_folders()) == 2
        # The real tuple is untouched by the patch above.
        assert bundle_layout.mpy_format_folders() == ("mpy6",)
