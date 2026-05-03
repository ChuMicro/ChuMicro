"""Tests for chumicro_deploy.preflight — `[tool.chumicro].requires_flash` discovery."""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy.preflight import find_libraries_requiring_flash


def _write_pyproject(
    directory: Path,
    *,
    name: str,
    requires_flash: bool | None = None,
) -> None:
    """Write a minimal pyproject.toml at *directory*.

    *requires_flash* ``None`` omits the ``[tool.chumicro]`` block
    entirely; ``True`` / ``False`` writes the explicit flag.
    """
    lines = [
        "[project]",
        f'name = "{name}"',
        'version = "0.0.0"',
    ]
    if requires_flash is not None:
        lines.extend(
            [
                "",
                "[tool.chumicro]",
                f"requires_flash = {str(requires_flash).lower()}",
            ],
        )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").write_text("\n".join(lines) + "\n")


class TestFindLibrariesRequiringFlash:
    """The pre-flight discovery walks host paths up to pyproject.toml's."""

    def test_empty_input_returns_empty(self):
        assert find_libraries_requiring_flash([]) == []

    def test_single_flagged_library(self, tmp_path: Path):
        """A host path under a directory whose pyproject says
        ``requires_flash = true`` surfaces the project name.
        """
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        _write_pyproject(lib, name="chumicro-mylib", requires_flash=True)
        result = find_libraries_requiring_flash([source_dir / "__init__.py"])
        assert result == ["chumicro-mylib"]

    def test_unflagged_library_excluded(self, tmp_path: Path):
        """A pyproject without the flag isn't surfaced."""
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        _write_pyproject(lib, name="chumicro-mylib", requires_flash=False)
        assert find_libraries_requiring_flash([source_dir / "__init__.py"]) == []

    def test_flag_absent_treated_as_false(self, tmp_path: Path):
        """A pyproject with no ``[tool.chumicro]`` block isn't surfaced."""
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        _write_pyproject(lib, name="chumicro-mylib")
        assert find_libraries_requiring_flash([source_dir / "__init__.py"]) == []

    def test_multiple_libraries_dedup_and_sorted(self, tmp_path: Path):
        """Two flagged libraries surface as a sorted list."""
        for sub_name, project_name, flag in [
            ("mqtt", "chumicro-mqtt", True),
            ("requests", "chumicro-requests", True),
            ("timing", "chumicro-timing", False),
        ]:
            lib = tmp_path / sub_name
            source_dir = lib / "src" / f"chumicro_{sub_name}"
            source_dir.mkdir(parents=True)
            (source_dir / "__init__.py").write_text("")
            _write_pyproject(lib, name=project_name, requires_flash=flag)

        host_paths = [
            tmp_path / "mqtt" / "src" / "chumicro_mqtt" / "__init__.py",
            tmp_path / "requests" / "src" / "chumicro_requests" / "__init__.py",
            tmp_path / "timing" / "src" / "chumicro_timing" / "__init__.py",
        ]
        result = find_libraries_requiring_flash(host_paths)
        assert result == ["chumicro-mqtt", "chumicro-requests"]

    def test_pyproject_dedup_across_files_in_same_lib(self, tmp_path: Path):
        """Two host paths under the same library only count once."""
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        (source_dir / "submodule.py").write_text("")
        _write_pyproject(lib, name="chumicro-mylib", requires_flash=True)

        result = find_libraries_requiring_flash(
            [source_dir / "__init__.py", source_dir / "submodule.py"],
        )
        assert result == ["chumicro-mylib"]

    def test_path_with_no_containing_pyproject_skipped(self, tmp_path: Path):
        """A host path with no ``pyproject.toml`` ancestor is skipped silently."""
        orphan = tmp_path / "orphan_dir"
        orphan.mkdir()
        (orphan / "code.py").write_text("")
        # No pyproject anywhere — silent skip, no exception.
        assert find_libraries_requiring_flash([orphan / "code.py"]) == []

    def test_malformed_pyproject_skipped(self, tmp_path: Path):
        """A pyproject.toml that fails to parse is treated as unflagged."""
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        # Write garbage that tomllib cannot parse.
        (lib / "pyproject.toml").write_text("[unterminated\n")
        assert find_libraries_requiring_flash([source_dir / "__init__.py"]) == []

    def test_flagged_pyproject_without_project_name_skipped(self, tmp_path: Path):
        """A pyproject with the flag but no [project].name returns nothing
        (defensive — every real chumicro library has a name).
        """
        lib = tmp_path / "mylib"
        source_dir = lib / "src" / "mylib"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("")
        # Write a pyproject with [tool.chumicro] but no [project] block.
        (lib / "pyproject.toml").write_text(
            "[tool.chumicro]\nrequires_flash = true\n",
        )
        assert find_libraries_requiring_flash([source_dir / "__init__.py"]) == []

    def test_walks_up_from_deeply_nested_path(self, tmp_path: Path):
        """Pre-flight finds the pyproject however deep the host path is."""
        lib = tmp_path / "mylib"
        deep = lib / "src" / "mylib" / "_adapters" / "deep" / "nested"
        deep.mkdir(parents=True)
        (deep / "leaf.py").write_text("")
        _write_pyproject(lib, name="chumicro-mylib", requires_flash=True)
        result = find_libraries_requiring_flash([deep / "leaf.py"])
        assert result == ["chumicro-mylib"]
