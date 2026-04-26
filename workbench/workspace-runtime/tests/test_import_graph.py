"""Tests for the workspace-shaped import-graph deploy source."""

from pathlib import Path

import pytest
from chumicro_msgpack import unpackb
from chumicro_workspace_runtime import (
    RUNTIME_CONFIG_DEVICE_PATH,
    WorkspaceConfigError,
    build_search_paths,
    read_library_sources,
    thing_import_graph_source,
)
from chumicro_workspace_runtime.workspace import WorkspaceLayout

# ---------------------------------------------------------------------------
# read_library_sources
# ---------------------------------------------------------------------------


class TestReadLibrarySources:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_library_sources(tmp_path / "absent.yml") == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("")
        assert read_library_sources(path) == {}

    def test_no_library_sources_block_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("defaults: {}\n")
        assert read_library_sources(path) == {}

    def test_returns_paths(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text(
            "library_sources:\n"
            "  chumicro_wifi: /home/me/dev/chumicro/libraries/wifi/src\n"
            "  shared_libs: ./local/checkout\n"
        )
        result = read_library_sources(path)
        assert result["chumicro_wifi"] == Path("/home/me/dev/chumicro/libraries/wifi/src")
        assert result["shared_libs"] == Path("./local/checkout")

    def test_top_level_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("- one\n- two\n")
        with pytest.raises(WorkspaceConfigError):
            read_library_sources(path)

    def test_library_sources_not_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("library_sources: not-a-mapping\n")
        with pytest.raises(WorkspaceConfigError):
            read_library_sources(path)

    def test_non_string_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("library_sources:\n  42: /some/path\n")
        with pytest.raises(WorkspaceConfigError):
            read_library_sources(path)

    def test_non_string_value_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "workspace.yml"
        path.write_text("library_sources:\n  foo:\n    not: a-string\n")
        with pytest.raises(WorkspaceConfigError):
            read_library_sources(path)


# ---------------------------------------------------------------------------
# build_search_paths
# ---------------------------------------------------------------------------


def _seed_workspace_root(tmp_path: Path, *, with_libs: bool = True,
                         with_packages: bool = True) -> WorkspaceLayout:
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    if with_libs:
        (tmp_path / "libs").mkdir()
    if with_packages:
        (tmp_path / "packages").mkdir()
    return WorkspaceLayout(root=tmp_path)


class TestBuildSearchPaths:
    def test_default_returns_libs_then_packages(self, tmp_path: Path) -> None:
        layout = _seed_workspace_root(tmp_path)
        result = build_search_paths(layout)
        assert result == [layout.libs_dir, layout.packages_dir]

    def test_skips_missing_dirs(self, tmp_path: Path) -> None:
        """libs/ + packages/ both absent → empty list."""
        layout = _seed_workspace_root(tmp_path, with_libs=False, with_packages=False)
        assert build_search_paths(layout) == []

    def test_library_sources_override_comes_first(self, tmp_path: Path) -> None:
        layout = _seed_workspace_root(tmp_path)
        override_dir = tmp_path / "checkouts" / "chumicro-wifi" / "src"
        override_dir.mkdir(parents=True)
        result = build_search_paths(
            layout, library_sources_override={"chumicro_wifi": override_dir},
        )
        assert result[0] == override_dir
        assert layout.libs_dir in result
        assert layout.packages_dir in result

    def test_extra_search_paths_appended_at_tail(self, tmp_path: Path) -> None:
        layout = _seed_workspace_root(tmp_path)
        extra = tmp_path / "extra"
        extra.mkdir()
        result = build_search_paths(layout, extra_search_paths=[extra])
        assert result[-1] == extra

    def test_dedupe_preserves_first_occurrence(self, tmp_path: Path) -> None:
        layout = _seed_workspace_root(tmp_path)
        result = build_search_paths(
            layout,
            library_sources_override={"foo": layout.libs_dir},
        )
        # libs/ appears once even though it shows up in both
        # the override map (under name 'foo') and the default.
        assert result.count(layout.libs_dir) == 1

    def test_library_sources_sorted_by_name_for_stability(self, tmp_path: Path) -> None:
        """Two invocations with the same map produce the same path order."""
        layout = _seed_workspace_root(tmp_path)
        zulu = tmp_path / "zulu"
        zulu.mkdir()
        alpha = tmp_path / "alpha"
        alpha.mkdir()
        result = build_search_paths(
            layout,
            library_sources_override={"zulu": zulu, "alpha": alpha},
        )
        # 'alpha' < 'zulu' alphabetically → alpha path comes first.
        assert result.index(alpha) < result.index(zulu)


# ---------------------------------------------------------------------------
# thing_import_graph_source — end to end
# ---------------------------------------------------------------------------


def _seed_thing_with_imports(tmp_path: Path) -> WorkspaceLayout:
    """Stage a workspace with a thing that imports from libs/."""
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    (tmp_path / "secrets.yml").write_text("\n")
    libs = tmp_path / "libs"
    libs.mkdir()
    (libs / "shared_helper.py").write_text(
        "def add(left, right):\n    return left + right\n"
    )
    (libs / "unused_helper.py").write_text(
        "def never_called():\n    return 42\n"
    )

    thing_dir = tmp_path / "things" / "back-porch"
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\n"
    )
    (thing_dir / "code.py").write_text(
        "import shared_helper\n"
        "print('result:', shared_helper.add(1, 2))\n"
    )
    return WorkspaceLayout(root=tmp_path)


class TestThingImportGraphSource:
    def test_ships_entrypoint_and_imported_modules(self, tmp_path: Path) -> None:
        workspace = _seed_thing_with_imports(tmp_path)
        thing_dir = workspace.thing_dir("back-porch")
        source = thing_import_graph_source(thing_dir, workspace=workspace)
        files = source.files()
        # Entrypoint lands at the device default.
        assert "/code.py" in files
        # Imported helper is staged under /lib/.
        assert "/lib/shared_helper.py" in files

    def test_skips_unimported_modules(self, tmp_path: Path) -> None:
        """unused_helper.py shouldn't ship — that's the whole point."""
        workspace = _seed_thing_with_imports(tmp_path)
        thing_dir = workspace.thing_dir("back-porch")
        source = thing_import_graph_source(thing_dir, workspace=workspace)
        files = source.files()
        assert "/lib/unused_helper.py" not in files

    def test_runtime_config_msgpack_rides_along(self, tmp_path: Path) -> None:
        """Slice 1's WithRuntimeConfig wraps the import graph too."""
        workspace = _seed_thing_with_imports(tmp_path)
        thing_dir = workspace.thing_dir("back-porch")
        source = thing_import_graph_source(thing_dir, workspace=workspace)
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi"]["ssid"] == "HomeNet"

    def test_library_sources_override_routes_through_external_path(
        self,
        tmp_path: Path,
    ) -> None:
        """library_sources: in workspace.yml lets a checkout shadow libs/."""
        # Set up a workspace whose libs/ has one version of a module
        # and an external path whose copy must win.
        external = tmp_path / "checkout"
        external.mkdir()
        (external / "shared_helper.py").write_text(
            "MARKER = 'from-external'\n"
            "def add(left, right):\n    return left + right\n"
        )

        (tmp_path / "workspace.yml").write_text(
            "library_sources:\n"
            f"  shared_helper: {external}\n"
        )
        (tmp_path / "secrets.yml").write_text("\n")
        libs = tmp_path / "libs"
        libs.mkdir()
        (libs / "shared_helper.py").write_text("MARKER = 'from-libs'\n")

        thing_dir = tmp_path / "things" / "back-porch"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[wifi]\nssid = 'x'\n")
        (thing_dir / "code.py").write_text("import shared_helper\n")

        workspace = WorkspaceLayout(root=tmp_path)
        source = thing_import_graph_source(thing_dir, workspace=workspace)
        files = source.files()
        # The external version wins over libs/.
        assert b"from-external" in files["/lib/shared_helper.py"]
        assert b"from-libs" not in files["/lib/shared_helper.py"]

    def test_main_py_entrypoint_works_for_micropython(
        self,
        tmp_path: Path,
    ) -> None:
        """Override entrypoint_filename + device_entrypoint for MP."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "secrets.yml").write_text("\n")
        thing_dir = tmp_path / "things" / "mp-thing"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[app]\n")
        (thing_dir / "main.py").write_text("print('mp')\n")
        workspace = WorkspaceLayout(root=tmp_path)

        source = thing_import_graph_source(
            thing_dir,
            workspace=workspace,
            entrypoint_filename="main.py",
            device_entrypoint="/main.py",
        )
        files = source.files()
        assert "/main.py" in files
        assert source.entrypoint() == "/main.py"

    def test_missing_entrypoint_raises(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        thing_dir = tmp_path / "things" / "empty"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[app]\n")
        workspace = WorkspaceLayout(root=tmp_path)
        with pytest.raises(FileNotFoundError):
            thing_import_graph_source(thing_dir, workspace=workspace)

    def test_extra_search_paths_used_for_resolution(
        self,
        tmp_path: Path,
    ) -> None:
        """Caller-supplied tail search path resolves modules not under libs/."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "secrets.yml").write_text("\n")
        external = tmp_path / "external"
        external.mkdir()
        (external / "extra_module.py").write_text("X = 1\n")

        thing_dir = tmp_path / "things" / "x"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[app]\n")
        (thing_dir / "code.py").write_text("import extra_module\n")
        workspace = WorkspaceLayout(root=tmp_path)

        source = thing_import_graph_source(
            thing_dir,
            workspace=workspace,
            extra_search_paths=[external],
        )
        files = source.files()
        assert "/lib/extra_module.py" in files

    def test_extra_modules_force_included(self, tmp_path: Path) -> None:
        """extra_modules forwards through to ImportGraphSource."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "secrets.yml").write_text("\n")
        libs = tmp_path / "libs"
        libs.mkdir()
        (libs / "dynamic_target.py").write_text("Y = 2\n")

        thing_dir = tmp_path / "things" / "x"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[app]\n")
        # Entrypoint never imports dynamic_target — only force-include picks it up.
        (thing_dir / "code.py").write_text("print('hi')\n")
        workspace = WorkspaceLayout(root=tmp_path)

        source = thing_import_graph_source(
            thing_dir,
            workspace=workspace,
            extra_modules=["dynamic_target"],
        )
        files = source.files()
        assert "/lib/dynamic_target.py" in files
