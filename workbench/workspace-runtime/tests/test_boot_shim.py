"""Tests for the boot-shim deploy pattern + on-device workspace_runtime."""

import sys
from pathlib import Path
from typing import Any

import pytest
from chumicro_msgpack import unpackb
from chumicro_workspace_runtime import (
    BOOT_MODULE_DEVICE_PATH,
    RUNTIME_CONFIG_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    THINGS_PACKAGE_INIT_DEVICE_PATH,
    boot_shim_files,
    build_active_py,
    load_workspace_runtime_payload,
    thing_boot_source,
)
from chumicro_workspace_runtime.workspace import WorkspaceLayout

# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestBuildActivePy:
    def test_writes_thing_name_constant(self) -> None:
        body = build_active_py("back-porch")
        assert 'THING_NAME = "back-porch"' in body

    def test_includes_warning_header(self) -> None:
        """The auto-overwritten warning must survive into the file body."""
        body = build_active_py("anything")
        assert "rewritten on each deploy" in body

    def test_thing_name_with_dashes_quoted(self) -> None:
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
        files = boot_shim_files(thing_name="x")
        assert "/code.py" in files
        assert "/main.py" not in files

    def test_main_py_override(self) -> None:
        files = boot_shim_files(thing_name="x", entrypoint_filename="main.py")
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_shim_source_matches_constant(self) -> None:
        files = boot_shim_files(thing_name="x")
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")

    def test_active_py_carries_thing_name(self) -> None:
        files = boot_shim_files(thing_name="garage-sensor")
        assert b'"garage-sensor"' in files["/active.py"]

    def test_workspace_runtime_payload_at_canonical_path(self) -> None:
        files = boot_shim_files(thing_name="x")
        assert BOOT_MODULE_DEVICE_PATH in files
        assert files[BOOT_MODULE_DEVICE_PATH] == load_workspace_runtime_payload()

    def test_things_package_marker_present(self) -> None:
        files = boot_shim_files(thing_name="x")
        assert THINGS_PACKAGE_INIT_DEVICE_PATH in files
        assert files[THINGS_PACKAGE_INIT_DEVICE_PATH] == b""

    def test_thing_subpackage_marker_present(self) -> None:
        """Each thing gets its own /lib/things/<name>/__init__.py."""
        files = boot_shim_files(thing_name="back-porch")
        assert "/lib/things/back-porch/__init__.py" in files


# ---------------------------------------------------------------------------
# On-device boot module — exec it under realistic stubs
# ---------------------------------------------------------------------------


class TestOnDeviceBoot:
    """Exec the payload + drive boot() with stub /active.py + thing module.

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
        thing_name: str | None,
        thing_app_body: str | None,
    ) -> dict[str, Any]:
        """Lay out an on-device-shaped tree under tmp_path.

        Uses ``monkeypatch.syspath_prepend`` (auto-restored on
        teardown) so consecutive tests don't leak ``active`` modules
        from each other's tmp_paths.  Cached modules are popped via
        monkeypatch.delitem so they're reset on teardown too.
        """
        # Mimic the on-device layout: /, /lib/, /lib/things/<name>/.
        if thing_name is not None:
            (tmp_path / "active.py").write_text(
                build_active_py(thing_name),
            )
            things_root = tmp_path / "things" / thing_name
            things_root.mkdir(parents=True)
            (tmp_path / "things" / "__init__.py").write_text("")
            (things_root / "__init__.py").write_text("")
            if thing_app_body is not None:
                (things_root / "app.py").write_text(thing_app_body)

        # syspath_prepend's auto-teardown restores sys.path cleanly.
        monkeypatch.syspath_prepend(str(tmp_path))
        # Drop any cached modules from previous runs.  Saving sys.modules
        # via monkeypatch lets pytest restore it on teardown.
        stale_names = [
            "active",
            "things",
            "workspace_runtime",
        ]
        if thing_name is not None:
            stale_names.append("things." + thing_name)
            stale_names.append("things." + thing_name + ".app")
        for stale in stale_names:
            sys.modules.pop(stale, None)

        namespace: dict[str, Any] = {"__name__": "workspace_runtime"}
        exec(  # noqa: S102 — exec'ing a known payload, scoped namespace
            compile(load_workspace_runtime_payload(), "<workspace_runtime>", "exec"),
            namespace,
        )
        return namespace

    def test_boot_runs_thing_app(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        thing_app_body = (
            "RUN_CALLED = []\n"
            "def run():\n"
            "    RUN_CALLED.append('yes')\n"
        )
        namespace = self._stage_runtime(
            tmp_path,
            monkeypatch,
            thing_name="thing-a",
            thing_app_body=thing_app_body,
        )
        namespace["boot"]()
        assert sys.modules["things.thing-a.app"].RUN_CALLED == ["yes"]

    def test_missing_active_py_raises_workspace_boot_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        namespace = self._stage_runtime(
            tmp_path, monkeypatch, thing_name=None, thing_app_body=None,
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "/active.py missing" in str(caught.value)

    def test_active_py_without_thing_name_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stage active.py with no THING_NAME.
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
        assert "no THING_NAME" in str(caught.value)

    def test_thing_app_missing_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stage active.py + things package but no app.py.
        namespace = self._stage_runtime(
            tmp_path, monkeypatch, thing_name="ghost", thing_app_body=None,
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "could not import" in str(caught.value)

    def test_thing_app_without_run_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        namespace = self._stage_runtime(
            tmp_path,
            monkeypatch,
            thing_name="thing-b",
            thing_app_body="OTHER_NAME = 'no run() defined'\n",
        )
        with pytest.raises(namespace["WorkspaceBootError"]) as caught:
            namespace["boot"]()
        assert "no run() function" in str(caught.value)


# ---------------------------------------------------------------------------
# thing_boot_source — the host-side packager
# ---------------------------------------------------------------------------


def _seed_thing_for_boot(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n"
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: shh\n")
    thing_dir = tmp_path / "things" / "back-porch"
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
    )
    (thing_dir / "app.py").write_text(
        "def run():\n    print('back-porch running')\n"
    )
    (thing_dir / "helpers.py").write_text(
        "VALUE = 1\n"
    )
    return WorkspaceLayout(root=tmp_path), thing_dir


class TestThingBootSource:
    def test_includes_shim_layer(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        assert "/code.py" in files
        assert "/active.py" in files
        assert BOOT_MODULE_DEVICE_PATH in files
        assert THINGS_PACKAGE_INIT_DEVICE_PATH in files
        assert "/lib/things/back-porch/__init__.py" in files

    def test_includes_thing_app_at_lib_path(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        assert "/lib/things/back-porch/app.py" in files
        assert files["/lib/things/back-porch/app.py"].startswith(b"def run")

    def test_includes_thing_helpers(self, tmp_path: Path) -> None:
        """Non-app.py files in the thing dir come along too."""
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        assert "/lib/things/back-porch/helpers.py" in files

    def test_skips_host_side_config_files(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        # config.toml is host-only, must not ship under /lib/things/.
        assert "/lib/things/back-porch/config.toml" not in files

    def test_skips_generated_dir(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        # Pre-create a stale _generated/ entry.
        (thing_dir / "_generated").mkdir()
        (thing_dir / "_generated" / "stale.bin").write_bytes(b"\x00")
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        assert "/lib/things/back-porch/_generated/stale.bin" not in files

    def test_runtime_config_msgpack_rides_along(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi"]["password"] == "shh"

    def test_entrypoint_is_code_py(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(thing_dir, workspace=workspace)
        assert source.entrypoint() == "/code.py"

    def test_main_py_entrypoint_for_micropython(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir, workspace=workspace, entrypoint_filename="main.py",
        )
        assert source.entrypoint() == "/main.py"
        files = source.files()
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_thing_name_override(self, tmp_path: Path) -> None:
        """Ship the same thing under a different active-name (multi-thing future)."""
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir, workspace=workspace, thing_name="renamed",
        )
        files = source.files()
        assert "/lib/things/renamed/app.py" in files
        assert "/lib/things/back-porch/app.py" not in files
        assert b'"renamed"' in files["/active.py"]

    def test_extra_excluded_skips_named_dir(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_thing_for_boot(tmp_path)
        (thing_dir / "notes").mkdir()
        (thing_dir / "notes" / "draft.md").write_text("draft\n")
        source = thing_boot_source(
            thing_dir, workspace=workspace, extra_excluded=("notes",),
        )
        files = source.files()
        assert "/lib/things/back-porch/notes/draft.md" not in files

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        thing_dir = tmp_path / "things" / "no-config"
        thing_dir.mkdir(parents=True)
        (thing_dir / "app.py").write_text("def run(): pass\n")
        workspace = WorkspaceLayout(root=tmp_path)
        with pytest.raises(FileNotFoundError):
            thing_boot_source(thing_dir, workspace=workspace)
