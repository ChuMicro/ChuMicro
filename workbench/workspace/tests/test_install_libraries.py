"""Tests for ``chumicro_workspace.install_libraries`` (gap 4)."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.install_libraries import (
    DEFAULT_GITHUB_ORG,
    EXPERIMENTAL_BUNDLE_REPO,
    STABLE_BUNDLE_REPO,
    build_circup_command,
    build_mip_commands,
    discover_chumicro_imports,
    import_name_to_package,
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
# build_circup_command
# ---------------------------------------------------------------------------


class TestBuildCircupCommand:
    def test_default_no_drive_path(self) -> None:
        command = build_circup_command(["chumicro-wifi", "chumicro-mqtt"])
        # Sorted, deterministic.
        assert command == ["circup", "install", "chumicro-mqtt", "chumicro-wifi"]

    def test_with_drive_path(self) -> None:
        command = build_circup_command(
            ["chumicro-wifi"], drive_path="/Volumes/CIRCUITPY",
        )
        assert command == [
            "circup", "--path", "/Volumes/CIRCUITPY", "install", "chumicro-wifi",
        ]

    def test_empty_list_still_returns_install(self) -> None:
        """Empty list — circup install with no args.  Caller decides whether to skip."""
        command = build_circup_command([])
        assert command == ["circup", "install"]


# ---------------------------------------------------------------------------
# build_mip_commands
# ---------------------------------------------------------------------------


class TestBuildMipCommands:
    def test_one_command_per_package(self) -> None:
        commands = build_mip_commands(["chumicro-wifi", "chumicro-mqtt"])
        assert len(commands) == 2

    def test_default_targets_stable_bundle(self) -> None:
        commands = build_mip_commands(["chumicro-wifi"])
        assert (
            f"github:{DEFAULT_GITHUB_ORG}/{STABLE_BUNDLE_REPO}/chumicro_wifi"
            in commands[0]
        )

    def test_experimental_bundle_target(self) -> None:
        commands = build_mip_commands(
            ["chumicro-wifi"], bundle_repo=EXPERIMENTAL_BUNDLE_REPO,
        )
        assert (
            f"github:{DEFAULT_GITHUB_ORG}/{EXPERIMENTAL_BUNDLE_REPO}/chumicro_wifi"
            in commands[0]
        )

    def test_address_emits_connect(self) -> None:
        commands = build_mip_commands(
            ["chumicro-wifi"], address="/dev/cu.usbmodem1",
        )
        assert "connect" in commands[0]
        assert "/dev/cu.usbmodem1" in commands[0]

    def test_no_address_omits_connect(self) -> None:
        commands = build_mip_commands(["chumicro-wifi"])
        assert "connect" not in commands[0]

    def test_underscored_package_name_in_url(self) -> None:
        """``chumicro-http-server`` → URL uses ``chumicro_http_server``."""
        commands = build_mip_commands(["chumicro-http-server"])
        assert "chumicro_http_server" in commands[0][-1]
        assert "chumicro-http-server" not in commands[0][-1]

    def test_packages_sorted_for_deterministic_order(self) -> None:
        """Same input set in any iter-order produces the same command list."""
        first = build_mip_commands(["chumicro-zeta", "chumicro-alpha"])
        second = build_mip_commands(["chumicro-alpha", "chumicro-zeta"])
        assert first == second
        # And alphabetical.
        assert "chumicro_alpha" in first[0][-1]
        assert "chumicro_zeta" in first[1][-1]

    def test_custom_org(self) -> None:
        commands = build_mip_commands(
            ["chumicro-wifi"], org="MyFork",
        )
        assert "github:MyFork/" in commands[0][-1]
