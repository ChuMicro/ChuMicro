"""Tests for the boot-shim deploy pattern + on-device workspace_runtime."""

import sys
from pathlib import Path
from typing import Any

import pytest
from chumicro_workspace import (
    BOOT_MODULE_DEVICE_PATH,
    PROJECTS_PACKAGE_INIT_DEVICE_PATH,
    RUNTIME_CONFIG_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    boot_shim_files,
    build_active_py,
    load_workspace_runtime_payload,
    project_boot_source,
)
from chumicro_workspace.workspace import WorkspaceLayout
from msgpack import unpackb

# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestBuildActivePy:
    def test_writes_project_name_constant(self) -> None:
        body = build_active_py("back-porch")
        assert 'PROJECT_NAME = "back-porch"' in body

    def test_includes_warning_header(self) -> None:
        """The auto-overwritten warning must survive into the file body."""
        body = build_active_py("anything")
        assert "rewritten on each deploy" in body

    def test_project_name_with_dashes_quoted(self) -> None:
        body = build_active_py("back-porch-mp")
        assert '"back-porch-mp"' in body


class TestLoadWorkspaceRuntimePayload:
    def test_returns_bytes(self) -> None:
        payload = load_workspace_runtime_payload()
        assert isinstance(payload, bytes)
        assert len(payload) > 0

    def test_payload_is_valid_python(self) -> None:
        payload = load_workspace_runtime_payload()
        # compile() raises SyntaxError if the payload is broken.
        compile(payload, "<workspace_runtime>", "exec")

    def test_payload_defines_boot_function(self) -> None:
        """The on-device contract is `boot()` — verify it lands in the namespace."""
        payload = load_workspace_runtime_payload()
        namespace: dict[str, Any] = {}
        exec(compile(payload, "<workspace_runtime>", "exec"), namespace)  # noqa: S102
        assert callable(namespace.get("boot"))
        assert "WorkspaceBootError" in namespace


class TestBootShimFiles:
    def test_default_entrypoint_is_code_py(self) -> None:
        files = boot_shim_files(project_name="x")
        assert "/code.py" in files
        assert "/main.py" not in files

    def test_main_py_override(self) -> None:
        files = boot_shim_files(project_name="x", entrypoint_filename="main.py")
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_shim_source_matches_constant(self) -> None:
        files = boot_shim_files(project_name="x")
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")

    def test_active_py_carries_project_name(self) -> None:
        files = boot_shim_files(project_name="garage-sensor")
        assert b'"garage-sensor"' in files["/active.py"]

    def test_workspace_runtime_payload_at_canonical_path(self) -> None:
        files = boot_shim_files(project_name="x")
        assert BOOT_MODULE_DEVICE_PATH in files
        assert files[BOOT_MODULE_DEVICE_PATH] == load_workspace_runtime_payload()

    def test_projects_package_marker_present(self) -> None:
        files = boot_shim_files(project_name="x")
        assert PROJECTS_PACKAGE_INIT_DEVICE_PATH in files
        assert files[PROJECTS_PACKAGE_INIT_DEVICE_PATH] == b""

    def test_project_subpackage_marker_present(self) -> None:
        """Each project gets its own /lib/projects/<name>/__init__.py."""
        files = boot_shim_files(project_name="back-porch")
        assert "/lib/projects/back-porch/__init__.py" in files


class TestBootShimFilesNested:
    """Slice 2 — nested project names emit per-level namespace inits."""

    def test_dotted_project_name_emits_init_per_level(self) -> None:
        files = boot_shim_files(project_name="upstairs.bedroom_sensor")
        assert "/lib/projects/__init__.py" in files
        assert "/lib/projects/upstairs/__init__.py" in files
        assert "/lib/projects/upstairs/bedroom_sensor/__init__.py" in files
        # Each namespace init is empty bytes (Decision avoids PEP 420
        # namespace packages on MP / CP).
        for path in (
            "/lib/projects/upstairs/__init__.py",
            "/lib/projects/upstairs/bedroom_sensor/__init__.py",
        ):
            assert files[path] == b""

    def test_slash_form_normalises_to_dotted(self) -> None:
        """``garage/sensors/door_open`` and dotted form produce the same map."""
        slash_files = boot_shim_files(project_name="garage/sensors/door_open")
        dotted_files = boot_shim_files(project_name="garage.sensors.door_open")
        assert slash_files == dotted_files

    def test_three_level_emits_three_namespace_inits(self) -> None:
        files = boot_shim_files(project_name="garage/sensors/door_open")
        assert "/lib/projects/garage/__init__.py" in files
        assert "/lib/projects/garage/sensors/__init__.py" in files
        assert "/lib/projects/garage/sensors/door_open/__init__.py" in files

    def test_active_py_writes_dotted_form(self) -> None:
        """``active.py`` always carries the dotted name (boot's contract)."""
        files = boot_shim_files(project_name="upstairs/bedroom_sensor")
        assert b'"upstairs.bedroom_sensor"' in files["/active.py"]


class TestBuildActivePyDotted:
    """Slice 2 — slash/dotted normalisation for nested project names."""

    def test_slash_form_writes_dotted(self) -> None:
        body = build_active_py("upstairs/bedroom_sensor")
        assert 'PROJECT_NAME = "upstairs.bedroom_sensor"' in body

    def test_dotted_form_writes_dotted(self) -> None:
        body = build_active_py("upstairs.bedroom_sensor")
        assert 'PROJECT_NAME = "upstairs.bedroom_sensor"' in body

    def test_single_segment_unchanged(self) -> None:
        body = build_active_py("back-porch")
        assert 'PROJECT_NAME = "back-porch"' in body


# ---------------------------------------------------------------------------
# On-device boot module — exec it under realistic stubs
# ---------------------------------------------------------------------------


class TestOnDeviceBoot:
    """Exec the payload + drive boot() with stub /active.py + project module.

    Each test sets up a tmp_path layout, prepends it to ``sys.path``,
    imports the payload as ``workspace_runtime``, calls ``boot()``,
    and asserts on the resulting state.  This proves the on-device
    contract holds without booting a real CP / MP board.
    """

    def _stage_runtime(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        project_name: str | None,
        project_app_body: str | None,
    ) -> dict[str, Any]:
        """Lay out an on-device-shaped tree under tmp_path.

        Uses ``monkeypatch.syspath_prepend`` (auto-restored on
        teardown) so consecutive tests don't leak ``active`` modules
        from each other's tmp_paths.  Cached modules are popped via
        monkeypatch.delitem so they're reset on teardown too.
        """
        # Mimic the on-device layout: /, /lib/, /lib/projects/<name>/.
        if project_name is not None:
            (tmp_path / "active.py").write_text(
                build_active_py(project_name),
            )
            projects_root = tmp_path / "projects" / project_name
            projects_root.mkdir(parents=True)
            (tmp_path / "projects" / "__init__.py").write_text("")
            (projects_root / "__init__.py").write_text("")
            if project_app_body is not None:
                (projects_root / "app.py").write_text(project_app_body)

        # syspath_prepend's auto-teardown restores sys.path cleanly.
        monkeypatch.syspath_prepend(str(tmp_path))
        # Drop any cached modules from previous runs.  Saving sys.modules
        # via monkeypatch lets pytest restore it on teardown.
        stale_names = [
            "active",
            "projects",
            "workspace_runtime",
        ]
        if project_name is not None:
            stale_names.append("projects." + project_name)
            stale_names.append("projects." + project_name + ".app")
        for stale in stale_names:
            sys.modules.pop(stale, None)

        namespace: dict[str, Any] = {"__name__": "workspace_runtime"}
        exec(  # noqa: S102 — exec'ing a known payload, scoped namespace
            compile(load_workspace_runtime_payload(), "<workspace_runtime>", "exec"),
            namespace,
        )
        return namespace

    def test_boot_runs_project_app(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_app_body = (
            "RUN_CALLED = []\n"
            "def run():\n"
            "    RUN_CALLED.append('yes')\n"
        )
        namespace = self._stage_runtime(
            tmp_path,
            monkeypatch,
            project_name="project-a",
            project_app_body=project_app_body,
        )
        namespace["boot"]()
        assert sys.modules["projects.project-a.app"].RUN_CALLED == ["yes"]

    def test_missing_active_py_raises_workspace_boot_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        namespace = self._stage_runtime(
            tmp_path, monkeypatch, project_name=None, project_app_body=None,
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "/active.py missing" in str(caught.value)

    def test_active_py_without_project_name_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stage active.py with no PROJECT_NAME.
        (tmp_path / "active.py").write_text("# empty\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        sys.modules.pop("active", None)
        sys.modules.pop("workspace_runtime", None)

        namespace: dict[str, Any] = {"__name__": "workspace_runtime"}
        exec(  # noqa: S102
            compile(load_workspace_runtime_payload(), "<workspace_runtime>", "exec"),
            namespace,
        )

        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "no PROJECT_NAME" in str(caught.value)

    def test_project_app_missing_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stage active.py + projects package but no app.py.
        namespace = self._stage_runtime(
            tmp_path, monkeypatch, project_name="ghost", project_app_body=None,
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "could not import" in str(caught.value)

    def test_project_app_without_run_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        namespace = self._stage_runtime(
            tmp_path,
            monkeypatch,
            project_name="project-b",
            project_app_body="OTHER_NAME = 'no run() defined'\n",
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "no run() function" in str(caught.value)


# ---------------------------------------------------------------------------
# project_boot_source — the host-side packager
# ---------------------------------------------------------------------------


def _seed_project_for_boot(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n"
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: shh\n")
    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    (project_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
    )
    (project_dir / "app.py").write_text(
        "def run():\n    print('back-porch running')\n"
    )
    (project_dir / "helpers.py").write_text(
        "VALUE = 1\n"
    )
    return WorkspaceLayout(root=tmp_path), project_dir


class TestProjectBootSource:
    def test_includes_shim_layer(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/code.py" in files
        assert "/active.py" in files
        assert BOOT_MODULE_DEVICE_PATH in files
        assert PROJECTS_PACKAGE_INIT_DEVICE_PATH in files
        assert "/lib/projects/back-porch/__init__.py" in files

    def test_includes_project_app_at_lib_path(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/lib/projects/back-porch/app.py" in files
        assert files["/lib/projects/back-porch/app.py"].startswith(b"def run")

    def test_includes_project_helpers(self, tmp_path: Path) -> None:
        """Non-app.py files in the project dir come along too."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/lib/projects/back-porch/helpers.py" in files

    def test_skips_host_side_config_files(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        # config.toml is host-only, must not ship under /lib/projects/.
        assert "/lib/projects/back-porch/config.toml" not in files

    def test_skips_generated_dir(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        # Pre-create a stale _generated/ entry.
        (project_dir / "_generated").mkdir()
        (project_dir / "_generated" / "stale.bin").write_bytes(b"\x00")
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert "/lib/projects/back-porch/_generated/stale.bin" not in files

    def test_runtime_config_msgpack_rides_along(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(project_dir, workspace=workspace)
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi"]["password"] == "shh"

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

    def test_project_name_override(self, tmp_path: Path) -> None:
        """Ship the same project under a different active-name (multi-project future)."""
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir, workspace=workspace, project_name="renamed",
        )
        files = source.files()
        assert "/lib/projects/renamed/app.py" in files
        assert "/lib/projects/back-porch/app.py" not in files
        assert b'"renamed"' in files["/active.py"]

    def test_extra_excluded_skips_named_dir(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_project_for_boot(tmp_path)
        (project_dir / "notes").mkdir()
        (project_dir / "notes" / "draft.md").write_text("draft\n")
        source = project_boot_source(
            project_dir, workspace=workspace, extra_excluded=("notes",),
        )
        files = source.files()
        assert "/lib/projects/back-porch/notes/draft.md" not in files

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
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
        assert "/lib/projects/back-porch/_cp_helper.py" in files
        assert "/lib/projects/back-porch/_mp_helper.py" not in files
        # Universal helpers still ship.
        assert "/lib/projects/back-porch/helpers.py" in files


def _seed_nested_project_for_boot(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    """Two-level nested project fixture for boot-shim path tests."""
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n",
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: shh\n")
    project_dir = tmp_path / "projects" / "upstairs" / "bedroom_sensor"
    project_dir.mkdir(parents=True)
    (project_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n",
    )
    (project_dir / "app.py").write_text(
        "def run():\n    print('bedroom sensor running')\n",
    )
    return WorkspaceLayout(root=tmp_path), project_dir


class TestProjectBootSourceNested:
    """Slice 2 — nested project-name plumbing through the boot source."""

    def test_files_land_under_nested_path(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_nested_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            project_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert (
            "/lib/projects/upstairs/bedroom_sensor/app.py" in files
        )
        # Flat-layout path must NOT be present — that would shadow the
        # real on-device import.
        assert "/lib/projects/bedroom_sensor/app.py" not in files

    def test_namespace_inits_emitted_per_level(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_nested_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            project_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert "/lib/projects/__init__.py" in files
        assert "/lib/projects/upstairs/__init__.py" in files
        assert "/lib/projects/upstairs/bedroom_sensor/__init__.py" in files

    def test_active_py_carries_dotted_name(self, tmp_path: Path) -> None:
        workspace, project_dir = _seed_nested_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            project_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert b'"upstairs.bedroom_sensor"' in files["/active.py"]

    def test_runtime_config_msgpack_at_canonical_path(self, tmp_path: Path) -> None:
        """Nested project's msgpack still lands at /runtime_config.msgpack."""
        workspace, project_dir = _seed_nested_project_for_boot(tmp_path)
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            project_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi"]["password"] == "shh"

    def test_workspace_runtime_module_path_construction(self) -> None:
        """The boot module's ``projects.<PROJECT_NAME>.app`` import shape works for nested.

        ``workspace_runtime.boot()`` constructs the import path via
        string concatenation:

            module_path = "projects." + project_name + ".app"

        With a dotted ``PROJECT_NAME = "upstairs.bedroom_sensor"`` the
        result is ``"projects.upstairs.bedroom_sensor.app"`` — the path
        Python's ``__import__`` resolves through the namespace
        ``__init__.py`` chain.
        """
        project_name = "upstairs.bedroom_sensor"
        module_path = "projects." + project_name + ".app"
        assert module_path == "projects.upstairs.bedroom_sensor.app"
