"""Tests for chumicro-dev.toml integration (gap 3(a))."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.chumicro_dev import (
    CHUMICRO_DEV_FILENAME,
    MANAGED_MARKER,
    discover_chumicro_libraries,
    read_chumicro_dev_path,
    sync_library_sources,
)

# ---------------------------------------------------------------------------
# read_chumicro_dev_path
# ---------------------------------------------------------------------------


class TestReadChumicroDevPath:
    def test_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        assert read_chumicro_dev_path(tmp_path) is None

    def test_returns_none_when_chumicro_path_unset(self, tmp_path: Path) -> None:
        """File present but key missing — not dev-mode."""
        (tmp_path / CHUMICRO_DEV_FILENAME).write_text("# placeholder\n")
        assert read_chumicro_dev_path(tmp_path) is None

    def test_relative_path_resolves_against_workspace_root(
        self, tmp_path: Path,
    ) -> None:
        sibling = tmp_path / "chumicro"
        sibling.mkdir()
        workspace = tmp_path / "my-workspace"
        workspace.mkdir()
        (workspace / CHUMICRO_DEV_FILENAME).write_text(
            'chumicro_path = "../chumicro"\n',
        )
        result = read_chumicro_dev_path(workspace)
        assert result == sibling.resolve()

    def test_absolute_path_returned_as_is(self, tmp_path: Path) -> None:
        sibling = tmp_path / "elsewhere" / "chumicro"
        sibling.mkdir(parents=True)
        workspace = tmp_path / "my-workspace"
        workspace.mkdir()
        (workspace / CHUMICRO_DEV_FILENAME).write_text(
            f'chumicro_path = "{sibling}"\n',
        )
        result = read_chumicro_dev_path(workspace)
        assert result == sibling

    def test_empty_string_path_returns_none(self, tmp_path: Path) -> None:
        """An empty ``chumicro_path = ""`` is treated as unset."""
        (tmp_path / CHUMICRO_DEV_FILENAME).write_text(
            'chumicro_path = ""\n',
        )
        assert read_chumicro_dev_path(tmp_path) is None


# ---------------------------------------------------------------------------
# discover_chumicro_libraries
# ---------------------------------------------------------------------------


def _seed_chumicro_library(
    chumicro_path: Path, libname: str, *, with_init: bool = True,
) -> Path:
    """Stage a synthetic chumicro library under chumicro_path/libraries/."""
    library_dir = chumicro_path / "libraries" / libname
    package_dir = library_dir / "src" / f"chumicro_{libname}"
    package_dir.mkdir(parents=True)
    if with_init:
        (package_dir / "__init__.py").write_text(f"# chumicro_{libname}\n")
    return library_dir


class TestDiscoverChumicroLibraries:
    def test_returns_empty_when_libraries_dir_missing(
        self, tmp_path: Path,
    ) -> None:
        assert discover_chumicro_libraries(tmp_path) == {}

    def test_finds_well_formed_libraries(self, tmp_path: Path) -> None:
        _seed_chumicro_library(tmp_path, "timing")
        _seed_chumicro_library(tmp_path, "wifi")
        result = discover_chumicro_libraries(tmp_path)
        assert set(result.keys()) == {"chumicro_timing", "chumicro_wifi"}
        assert result["chumicro_timing"] == (
            tmp_path / "libraries" / "timing" / "src"
        )

    def test_skips_library_without_init_py(self, tmp_path: Path) -> None:
        """Half-scaffolded library (src exists, __init__.py missing) is skipped."""
        _seed_chumicro_library(tmp_path, "timing", with_init=False)
        _seed_chumicro_library(tmp_path, "wifi")
        result = discover_chumicro_libraries(tmp_path)
        assert "chumicro_timing" not in result
        assert "chumicro_wifi" in result

    def test_skips_library_without_src_dir(self, tmp_path: Path) -> None:
        """A bare ``libraries/foo/`` with no ``src/`` is skipped."""
        (tmp_path / "libraries" / "bare").mkdir(parents=True)
        _seed_chumicro_library(tmp_path, "wifi")
        result = discover_chumicro_libraries(tmp_path)
        assert "chumicro_bare" not in result
        assert "chumicro_wifi" in result

    def test_skips_library_with_mismatched_package_name(
        self, tmp_path: Path,
    ) -> None:
        """``libraries/wifi/src/wrong_name/`` doesn't match the convention."""
        odd_dir = tmp_path / "libraries" / "wifi" / "src" / "wrong_name"
        odd_dir.mkdir(parents=True)
        (odd_dir / "__init__.py").touch()
        result = discover_chumicro_libraries(tmp_path)
        assert result == {}

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        """Dotfile / hidden directories are skipped."""
        hidden = tmp_path / "libraries" / ".hidden"
        (hidden / "src" / "chumicro_.hidden").mkdir(parents=True)
        _seed_chumicro_library(tmp_path, "wifi")
        result = discover_chumicro_libraries(tmp_path)
        assert "chumicro_.hidden" not in result
        assert "chumicro_wifi" in result

    def test_skips_files_in_libraries_dir(self, tmp_path: Path) -> None:
        """A README at libraries/ doesn't trip the walk."""
        (tmp_path / "libraries").mkdir()
        (tmp_path / "libraries" / "README.md").write_text("# libraries\n")
        _seed_chumicro_library(tmp_path, "wifi")
        result = discover_chumicro_libraries(tmp_path)
        assert "chumicro_wifi" in result


# ---------------------------------------------------------------------------
# sync_library_sources
# ---------------------------------------------------------------------------


class TestSyncLibrarySources:
    def test_creates_workspace_yaml_when_missing(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        libraries = {"chumicro_timing": tmp_path / "chumicro/libraries/timing/src"}
        changed = sync_library_sources(workspace_yaml, libraries)
        assert changed is True
        assert workspace_yaml.is_file()
        body = workspace_yaml.read_text()
        assert "library_sources:" in body
        assert "chumicro_timing:" in body

    def test_writes_managed_marker_comment(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspace.yml"
        libraries = {"chumicro_timing": tmp_path / "chumicro/libraries/timing/src"}
        sync_library_sources(workspace_yaml, libraries)
        body = workspace_yaml.read_text()
        assert MANAGED_MARKER in body

    def test_writes_relative_paths_when_possible(self, tmp_path: Path) -> None:
        """Sibling-checkout paths render as ``../chumicro/...`` in the yaml."""
        sibling = tmp_path / "chumicro"
        (sibling / "libraries" / "timing" / "src" / "chumicro_timing").mkdir(
            parents=True,
        )
        workspace = tmp_path / "my-workspace"
        workspace.mkdir()
        workspace_yaml = workspace / "workspace.yml"
        libraries = {
            "chumicro_timing": sibling / "libraries" / "timing" / "src",
        }
        sync_library_sources(workspace_yaml, libraries)
        body = workspace_yaml.read_text()
        # Walk-up form preferred over absolute path.
        assert "../chumicro/libraries/timing/src" in body

    def test_keys_sorted_alphabetically(self, tmp_path: Path) -> None:
        """Block is diff-stable: sorted keys regardless of input order."""
        workspace_yaml = tmp_path / "workspace.yml"
        libraries = {
            "chumicro_zeta": tmp_path / "z/src",
            "chumicro_alpha": tmp_path / "a/src",
        }
        sync_library_sources(workspace_yaml, libraries)
        body = workspace_yaml.read_text()
        assert body.index("chumicro_alpha") < body.index("chumicro_zeta")

    def test_idempotent_returns_false_on_no_change(
        self, tmp_path: Path,
    ) -> None:
        """Re-running with the same libraries returns False (no write)."""
        workspace_yaml = tmp_path / "workspace.yml"
        libraries = {"chumicro_timing": tmp_path / "chumicro/libraries/timing/src"}
        first = sync_library_sources(workspace_yaml, libraries)
        second = sync_library_sources(workspace_yaml, libraries)
        assert first is True
        assert second is False

    def test_replaces_existing_library_sources_block(
        self, tmp_path: Path,
    ) -> None:
        """A prior library_sources: (user-edited or stale) is overwritten."""
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "defaults:\n  wifi:\n    hostname_prefix: chu-\n"
            "library_sources:\n"
            "  chumicro_old: /tmp/somewhere/old\n",
        )
        libraries = {"chumicro_timing": tmp_path / "chumicro/libraries/timing/src"}
        changed = sync_library_sources(workspace_yaml, libraries)
        assert changed is True
        body = workspace_yaml.read_text()
        assert "chumicro_old" not in body
        assert "chumicro_timing" in body

    def test_preserves_other_top_level_keys(self, tmp_path: Path) -> None:
        """defaults: + comments survive the rewrite."""
        workspace_yaml = tmp_path / "workspace.yml"
        workspace_yaml.write_text(
            "# user-authored comment above defaults\n"
            "defaults:\n"
            "  wifi:\n"
            "    hostname_prefix: chu-\n"
            "  custom_key: value\n",
        )
        libraries = {"chumicro_timing": tmp_path / "chumicro/libraries/timing/src"}
        sync_library_sources(workspace_yaml, libraries)
        body = workspace_yaml.read_text()
        assert "user-authored comment" in body
        assert "hostname_prefix: chu-" in body
        assert "custom_key: value" in body
        assert "chumicro_timing:" in body

    def test_block_round_trips_through_read_library_sources(
        self, tmp_path: Path,
    ) -> None:
        """The block we write must parse cleanly via the existing reader."""
        from chumicro_workspace.import_graph import (  # noqa: PLC0415
            read_library_sources,
        )

        workspace_yaml = tmp_path / "workspace.yml"
        sibling_source_dir = tmp_path / "chumicro" / "libraries" / "timing" / "src"
        sibling_source_dir.mkdir(parents=True)
        libraries = {"chumicro_timing": sibling_source_dir}
        sync_library_sources(workspace_yaml, libraries)
        parsed = read_library_sources(workspace_yaml)
        assert "chumicro_timing" in parsed
