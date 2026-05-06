"""Tests for the simplified boot-shim deploy pattern.

The boot shim is one synthesised entrypoint file (``/code.py`` for
CircuitPython, ``/main.py`` for MicroPython) that imports the
project's ``app.run`` and calls it.  Project files land at the
device root.  No ``active.py``, no ``/lib/workspace_runtime/``,
no ``/lib/projects/<name>/`` namespace — chumicro is one-project-per-
board.

History: an earlier multi-project layout used ``active.py`` as a
project-name selector + a ``workspace_runtime.boot()`` dispatcher.
F5 of the 2026-05-06 verification pass dropped that complexity in
favour of one-project-per-board with a synthesised three-line shim.
"""

from pathlib import Path

import pytest
from chumicro_workspace import (
    RUNTIME_CONFIG_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    boot_shim_files,
    project_app_exports_run,
    project_boot_source,
    project_boot_with_import_graph_source,
)
from chumicro_workspace.workspace import WorkspaceLayout
from msgpack import unpackb

# ---------------------------------------------------------------------------
# project_app_exports_run — the AST-based detection used by auto-detect
# ---------------------------------------------------------------------------


class TestProjectAppExportsRun:
    def test_returns_true_when_app_defines_run(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "def run():\n    print('ok')\n",
        )
        assert project_app_exports_run(tmp_path) is True

    def test_returns_true_when_app_defines_async_run(
        self, tmp_path: Path,
    ) -> None:
        (tmp_path / "app.py").write_text(
            "async def run():\n    pass\n",
        )
        assert project_app_exports_run(tmp_path) is True

    def test_returns_false_when_app_lacks_run(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "def go():\n    pass\n",
        )
        assert project_app_exports_run(tmp_path) is False

    def test_returns_false_when_app_missing(self, tmp_path: Path) -> None:
        assert project_app_exports_run(tmp_path) is False

    def test_returns_false_on_syntax_error(self, tmp_path: Path) -> None:
        """A malformed ``app.py`` shouldn't crash detection.

        The runtime can't run a syntax-broken file anyway; the
        deploy command's error message will surface the problem
        when the user actually tries to run the project.
        """
        (tmp_path / "app.py").write_text("def run(:\n    pass\n")
        assert project_app_exports_run(tmp_path) is False

    def test_run_must_be_top_level(self, tmp_path: Path) -> None:
        """``run`` defined inside a class doesn't count.

        Auto-detect's contract is "boot-shim mode requires a top-
        level ``run`` callable" — methods don't satisfy that.
        """
        (tmp_path / "app.py").write_text(
            "class Foo:\n    def run(self):\n        pass\n",
        )
        assert project_app_exports_run(tmp_path) is False


# ---------------------------------------------------------------------------
# boot_shim_files — the synthesised shim
# ---------------------------------------------------------------------------


class TestBootShimFiles:
    def test_default_entrypoint_is_code_py(self) -> None:
        files = boot_shim_files()
        assert "/code.py" in files
        assert "/main.py" not in files

    def test_main_py_override_for_micropython(self) -> None:
        files = boot_shim_files(entrypoint_filename="main.py")
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_shim_source_matches_constant(self) -> None:
        files = boot_shim_files()
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")

    def test_shim_calls_app_run(self) -> None:
        """The synthesised shim must import ``run`` from ``app`` and call it.

        This is the on-device contract — the user's ``app.py`` exports
        ``run()``; the firmware boots ``code.py``/``main.py``; the shim
        is the bridge.
        """
        body = SHIM_ENTRYPOINT_SOURCE
        assert "from app import run" in body
        # Whatever the alias name is, it has to actually be called.
        assert "_run()" in body or "run()" in body

    def test_shim_only_emits_runtime_matching_entrypoint(self) -> None:
        """Only the target-matching file is synthesised — never both.

        Beginners deploy to one runtime per board.  Speculatively
        shipping both ``/code.py`` and ``/main.py`` for "future
        re-flashing" is YAGNI.
        """
        cp_files = boot_shim_files(entrypoint_filename="code.py")
        mp_files = boot_shim_files(entrypoint_filename="main.py")
        assert set(cp_files) == {"/code.py"}
        assert set(mp_files) == {"/main.py"}


# ---------------------------------------------------------------------------
# project_boot_source — the host-side packager
# ---------------------------------------------------------------------------


def _seed_project_for_boot(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    (tmp_path / "workspace.yml").write_text("# workspace machinery only\n")
    (tmp_path / "secrets.toml").write_text(
        "[wifi]\nhostname_prefix = 'chu-'\npassword = 'shh'\n",
    )
    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    (project_dir / "project_config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\n",
    )
    (project_dir / "app.py").write_text(
        "def run():\n    print('back-porch running')\n",
    )
    (project_dir / "helpers.py").write_text("VALUE = 1\n")
    return WorkspaceLayout(root=tmp_path), project_dir


class TestProjectBootSource:
    def test_includes_shim(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/code.py" in files
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")

    def test_app_lands_at_device_root(self, tmp_path: Path) -> None:
        """``app.py`` ships at ``/app.py`` — no ``/lib/projects/`` prefix."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/app.py" in files
        assert files["/app.py"].startswith(b"def run")

    def test_project_helpers_at_device_root(self, tmp_path: Path) -> None:
        """Sibling project modules ship at the device root, not under /lib/."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/helpers.py" in files

    def test_no_legacy_active_py(self, tmp_path: Path) -> None:
        """``active.py`` is gone — confirm it never lands."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/active.py" not in files

    def test_no_legacy_workspace_runtime(self, tmp_path: Path) -> None:
        """The on-device ``workspace_runtime`` payload is gone."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert not any(
            path.startswith("/lib/workspace_runtime/") for path in files
        )

    def test_no_legacy_lib_projects_namespace(self, tmp_path: Path) -> None:
        """Project files are at root, not under /lib/projects/<name>/."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert not any(path.startswith("/lib/projects/") for path in files)

    def test_skips_host_side_config_files(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        # config.toml is host-only; must not land on the device.
        assert "/config.toml" not in files

    def test_skips_generated_dir(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        (project_dir / "_generated").mkdir()
        (project_dir / "_generated" / "stale.bin").write_bytes(b"\x00")
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/_generated/stale.bin" not in files

    def test_runtime_config_msgpack_rides_along(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi.password"] == "shh"

    def test_entrypoint_is_code_py(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        assert source.entrypoint() == "/code.py"

    def test_main_py_entrypoint_for_micropython(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir, workspace=workspace, entrypoint_filename="main.py",
        )
        assert source.entrypoint() == "/main.py"
        files = source.files()
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_extra_excluded_skips_named_dir(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        (project_dir / "notes").mkdir()
        (project_dir / "notes" / "draft.md").write_text("draft\n")
        source = project_boot_source(
            project_dir, workspace=workspace, extra_excluded=("notes",),
        )
        files = source.files()
        assert "/notes/draft.md" not in files

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("# machinery only\n")
        (tmp_path / "secrets.toml").write_text("")
        project_dir = tmp_path / "projects" / "no-config"
        project_dir.mkdir(parents=True)
        (project_dir / "app.py").write_text("def run(): pass\n")
        workspace = WorkspaceLayout(root=tmp_path)
        with pytest.raises(FileNotFoundError):
            project_boot_source(project_dir, workspace=workspace)

    def test_target_runtime_drops_wrong_runtime_project_files(
        self, tmp_path: Path,
    ) -> None:
        """Decision 0044 — boot-shim layout filters project-local ``.py`` markers."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        (project_dir / "_cp_helper.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (project_dir / "_mp_helper.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        source = project_boot_source(
            project_dir, workspace=workspace, target_runtime="circuitpython",
        )
        files = source.files()
        assert "/_cp_helper.py" in files
        assert "/_mp_helper.py" not in files
        # Universal helpers still ship.
        assert "/helpers.py" in files


# ---------------------------------------------------------------------------
# Boot-shim + import-graph composition
# ---------------------------------------------------------------------------


def _seed_workspace_with_libraries(
    tmp_path: Path,
) -> tuple[WorkspaceLayout, Path]:
    """Workspace where the project imports libraries from ``shared/``.

    Layout::

        tmp_path/
            workspace.yml              (workspace machinery — host-only)
            secrets.toml               (gitignored device defaults + creds)
            shared/
                external_lib.py        (importable as ``external_lib``)
                unused_lib.py          (NOT imported — must not ship)
            projects/back-porch/
                project_config.toml
                app.py                 (imports external_lib + helpers)
                helpers.py             (imports external_lib indirectly)
    """
    (tmp_path / "workspace.yml").write_text("# machinery only\n")
    (tmp_path / "secrets.toml").write_text(
        "[wifi]\nhostname_prefix = 'chu-'\npassword = 'shh'\n",
    )
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "external_lib.py").write_text("def helper(): pass\n")
    (shared / "unused_lib.py").write_text("# never imported\n")
    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    (project_dir / "project_config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\n",
    )
    (project_dir / "app.py").write_text(
        "import external_lib\n"
        "import helpers\n"
        "def run():\n"
        "    helpers.go()\n",
    )
    (project_dir / "helpers.py").write_text(
        "import external_lib\n"
        "def go(): pass\n",
    )
    return WorkspaceLayout(root=tmp_path), project_dir


class TestProjectBootWithImportGraphSource:
    def test_includes_shim(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/code.py" in files
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")

    def test_app_at_device_root(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/app.py" in files

    def test_ships_imported_library(self, tmp_path: Path) -> None:
        """A `shared/` module reached from app.py lands at /lib/<name>.py."""
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/lib/external_lib.py" in files

    def test_skips_unimported_library(self, tmp_path: Path) -> None:
        """Modules outside the AST walk's reachable set don't ship."""
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/lib/unused_lib.py" not in files

    def test_does_not_duplicate_project_local_files(
        self, tmp_path: Path,
    ) -> None:
        """``helpers.py`` ships at /helpers.py only, not /lib/helpers.py.

        The import-graph walker reaches ``helpers.py`` because
        ``project_dir`` is a search path, but its parallel
        ``/lib/helpers.py`` landing is dead weight (project code
        resolves at the device root, not under ``/lib/``).  The
        combined source filters it out.
        """
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/helpers.py" in files
        assert "/lib/helpers.py" not in files

    def test_app_py_not_duplicated(self, tmp_path: Path) -> None:
        """``app.py`` ships at /app.py only — the import-graph walker
        reads it as the entrypoint but its parallel /lib/app.py landing
        is filtered.
        """
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert "/app.py" in files
        assert "/lib/app.py" not in files

    def test_entrypoint_is_boot_shim_code_py(self, tmp_path: Path) -> None:
        """The combined entrypoint is the boot-shim's /code.py shim."""
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        assert source.entrypoint() == "/code.py"

    def test_main_py_entrypoint_for_micropython(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
            entrypoint_filename="main.py",
        )
        assert source.entrypoint() == "/main.py"
        files = source.files()
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_runtime_config_msgpack_rides_along(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace,
        )
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi.password"] == "shh"

    def test_missing_project_entrypoint_raises(self, tmp_path: Path) -> None:
        """No app.py under the project directory is a clear failure."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        project_dir = tmp_path / "projects" / "no-app"
        project_dir.mkdir(parents=True)
        (project_dir / "config.toml").write_text("[wifi]\n")
        # No app.py.
        workspace = WorkspaceLayout(root=tmp_path)
        with pytest.raises(FileNotFoundError, match="app.py"):
            project_boot_with_import_graph_source(
                project_dir, workspace=workspace,
            )

    def test_target_runtime_filters_both_layers(self, tmp_path: Path) -> None:
        """Decision 0044 — runtime marker drops files on both inner sources."""
        workspace, project_dir = _seed_workspace_with_libraries(tmp_path)
        # Runtime-marked sibling under the project — boot-shim should drop it.
        (project_dir / "_mp_only.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )
        # Runtime-marked module in shared/ — import-graph should drop it
        # (and not walk it, even if app.py imports it).
        (tmp_path / "shared" / "mp_only_lib.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n'
            "VALUE = 1\n",
        )

        source = project_boot_with_import_graph_source(
            project_dir, workspace=workspace, target_runtime="circuitpython",
        )
        files = source.files()
        # Boot-shim filter: project file with mp-only marker dropped.
        assert "/_mp_only.py" not in files
        # Import-graph filter: mp-only library not shipped.
        assert "/lib/mp_only_lib.py" not in files
        # Universal entries still present.
        assert "/lib/external_lib.py" in files
        assert "/app.py" in files
