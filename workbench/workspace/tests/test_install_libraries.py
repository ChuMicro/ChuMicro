"""Tests for ``chumicro_workspace.install_libraries`` (gap 4)."""

from __future__ import annotations

import sys
from pathlib import Path

from chumicro_workspace.install_libraries import (
    DEFAULT_GITHUB_ORG,
    EXPERIMENTAL_BUNDLE_REPO,
    LIBRARIES_CACHE_DIRNAME,
    STABLE_BUNDLE_REPO,
    build_mip_fetch_command,
    build_pip_fetch_command,
    discover_chumicro_imports,
    import_name_to_package,
    local_src_dir,
)

# ---------------------------------------------------------------------------
# discover_chumicro_imports
# ---------------------------------------------------------------------------


class TestDiscoverChumicroImports:
    def test_finds_plain_import(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("import chumicro_wifi\n")
        assert discover_chumicro_imports(tmp_path) == {"chumicro_wifi"}

    def test_finds_import_with_alias(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("import chumicro_wifi as wifi\n")
        assert discover_chumicro_imports(tmp_path) == {"chumicro_wifi"}

    def test_finds_multiple_imports_on_one_line(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "import chumicro_wifi, chumicro_mqtt\n",
        )
        assert discover_chumicro_imports(tmp_path) == {
            "chumicro_wifi", "chumicro_mqtt",
        }

    def test_finds_from_import(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "from chumicro_kvstore import open_store\n",
        )
        assert discover_chumicro_imports(tmp_path) == {"chumicro_kvstore"}

    def test_finds_submodule_import_returns_top_level(
        self, tmp_path: Path,
    ) -> None:
        """``from chumicro_runner.task import X`` reduces to ``chumicro_runner``."""
        (tmp_path / "app.py").write_text(
            "from chumicro_runner.task import TaskHandle\n",
        )
        assert discover_chumicro_imports(tmp_path) == {"chumicro_runner"}

    def test_walks_subdirectories(self, tmp_path: Path) -> None:
        """Project-internal modules under nested dirs are walked too."""
        (tmp_path / "app.py").write_text(
            "from . import sensors\n",
        )
        sensors_dir = tmp_path / "sensors"
        sensors_dir.mkdir()
        (sensors_dir / "temp.py").write_text(
            "import chumicro_timing\n",
        )
        assert discover_chumicro_imports(tmp_path) == {"chumicro_timing"}

    def test_skips_non_chumicro_imports(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "import os\n"
            "import json\n"
            "from typing import Any\n"
            "import requests  # third-party non-chumicro\n",
        )
        assert discover_chumicro_imports(tmp_path) == set()

    def test_skips_relative_imports(self, tmp_path: Path) -> None:
        """``from . import foo`` and ``from ..bar import baz`` are project-internal."""
        (tmp_path / "app.py").write_text(
            "from . import sensors\n"
            "from ..util import helper\n",
        )
        assert discover_chumicro_imports(tmp_path) == set()

    def test_skips_files_with_syntax_errors(self, tmp_path: Path) -> None:
        """Broken Python doesn't trip the walk — user's bug, surfaced elsewhere."""
        (tmp_path / "broken.py").write_text("def oops(:\n")
        (tmp_path / "ok.py").write_text("import chumicro_wifi\n")
        assert discover_chumicro_imports(tmp_path) == {"chumicro_wifi"}

    def test_returns_empty_for_empty_project(self, tmp_path: Path) -> None:
        assert discover_chumicro_imports(tmp_path) == set()

    def test_dedupes_imports_across_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("import chumicro_wifi\n")
        (tmp_path / "b.py").write_text("from chumicro_wifi import connect\n")
        assert discover_chumicro_imports(tmp_path) == {"chumicro_wifi"}


# ---------------------------------------------------------------------------
# import_name_to_package
# ---------------------------------------------------------------------------


class TestImportNameToPackage:
    def test_simple(self) -> None:
        assert import_name_to_package("chumicro_kvstore") == "chumicro-kvstore"

    def test_multiple_underscores(self) -> None:
        assert import_name_to_package("chumicro_http_server") == "chumicro-http-server"


# ---------------------------------------------------------------------------
# local_src_dir
# ---------------------------------------------------------------------------


class TestLocalSrcDir:
    def test_maps_import_name_to_cache_src_dir(self, tmp_path: Path) -> None:
        assert local_src_dir(tmp_path, "chumicro_kvstore") == (
            tmp_path / LIBRARIES_CACHE_DIRNAME / "kvstore" / "src"
        )

    def test_strips_only_the_chumicro_prefix(self, tmp_path: Path) -> None:
        """``chumicro_http_server`` → ``_libraries/http_server/src``."""
        assert local_src_dir(tmp_path, "chumicro_http_server") == (
            tmp_path / LIBRARIES_CACHE_DIRNAME / "http_server" / "src"
        )

    def test_src_child_is_the_importable_package(self, tmp_path: Path) -> None:
        """The dir maps 1:1 to a ``library_sources:`` value — its child
        is ``chumicro_<name>/``, so the path is what the import-graph
        walker roots on.
        """
        src_dir = local_src_dir(tmp_path, "chumicro_wifi")
        assert src_dir.name == "src"
        assert src_dir.parent.name == "wifi"


# ---------------------------------------------------------------------------
# build_pip_fetch_command (primary backend)
# ---------------------------------------------------------------------------


class TestBuildPipFetchCommand:
    def test_targets_dir_under_active_interpreter(self, tmp_path: Path) -> None:
        target = tmp_path / "_libraries" / "wifi" / "src"
        command = build_pip_fetch_command("chumicro-wifi", target)
        assert command == [
            sys.executable, "-m", "pip", "install",
            "--target", str(target), "--upgrade", "chumicro-wifi",
        ]

    def test_no_board_or_circup_token(self, tmp_path: Path) -> None:
        """Host-local only — never circup / a drive / a serial port."""
        command = build_pip_fetch_command("chumicro-mqtt", tmp_path)
        assert "circup" not in command
        assert "--path" not in command
        assert all("/dev/" not in part for part in command)


# ---------------------------------------------------------------------------
# build_mip_fetch_command (download-to-local fallback)
# ---------------------------------------------------------------------------


class TestBuildMipFetchCommand:
    def test_default_targets_stable_bundle_locally(self, tmp_path: Path) -> None:
        command = build_mip_fetch_command("chumicro_wifi", tmp_path)
        assert command[:4] == ["mpremote", "mip", "install", "--target"]
        assert str(tmp_path) in command
        assert (
            f"github:{DEFAULT_GITHUB_ORG}/{STABLE_BUNDLE_REPO}/chumicro_wifi"
            == command[-1]
        )

    def test_experimental_bundle_target(self, tmp_path: Path) -> None:
        command = build_mip_fetch_command(
            "chumicro_wifi", tmp_path, bundle_repo=EXPERIMENTAL_BUNDLE_REPO,
        )
        assert (
            f"github:{DEFAULT_GITHUB_ORG}/{EXPERIMENTAL_BUNDLE_REPO}/chumicro_wifi"
            == command[-1]
        )

    def test_never_connects_to_a_board(self, tmp_path: Path) -> None:
        """``--target`` writes the host; mip must not ``connect`` a port."""
        command = build_mip_fetch_command("chumicro_wifi", tmp_path)
        assert "connect" not in command
        assert all("/dev/" not in part for part in command)

    def test_custom_org(self, tmp_path: Path) -> None:
        command = build_mip_fetch_command(
            "chumicro_wifi", tmp_path, org="MyFork",
        )
        assert command[-1].startswith("github:MyFork/")
