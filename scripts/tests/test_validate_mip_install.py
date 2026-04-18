"""Tests for validate_mip_install.py — mip install validation helpers."""

from pathlib import Path

from validate_mip_install import (
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
