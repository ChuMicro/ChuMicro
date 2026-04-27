"""Tests for the boot-shim deploy pattern + on-device workspace_runtime."""

import sys
from pathlib import Path
from typing import Any

import pytest
from chumicro_msgpack import unpackb
from chumicro_workspace import (
    BOOT_MODULE_DEVICE_PATH,
    RUNTIME_CONFIG_DEVICE_PATH,
    SHIM_ENTRYPOINT_SOURCE,
    THINGS_PACKAGE_INIT_DEVICE_PATH,
    boot_shim_files,
    build_active_py,
    build_switch_files,
    load_workspace_runtime_payload,
    multi_thing_boot_files,
    multi_thing_boot_source,
    switch_source,
    thing_boot_source,
)
from chumicro_workspace.workspace import WorkspaceLayout

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


class TestBootShimFilesNested:
    """Slice 2 — nested thing names emit per-level namespace inits."""

    def test_dotted_thing_name_emits_init_per_level(self) -> None:
        files = boot_shim_files(thing_name="upstairs.bedroom_sensor")
        assert "/lib/things/__init__.py" in files
        assert "/lib/things/upstairs/__init__.py" in files
        assert "/lib/things/upstairs/bedroom_sensor/__init__.py" in files
        # Each namespace init is empty bytes (Decision avoids PEP 420
        # namespace packages on MP / CP).
        for path in (
            "/lib/things/upstairs/__init__.py",
            "/lib/things/upstairs/bedroom_sensor/__init__.py",
        ):
            assert files[path] == b""

    def test_slash_form_normalises_to_dotted(self) -> None:
        """``garage/sensors/door_open`` and dotted form produce the same map."""
        slash_files = boot_shim_files(thing_name="garage/sensors/door_open")
        dotted_files = boot_shim_files(thing_name="garage.sensors.door_open")
        assert slash_files == dotted_files

    def test_three_level_emits_three_namespace_inits(self) -> None:
        files = boot_shim_files(thing_name="garage/sensors/door_open")
        assert "/lib/things/garage/__init__.py" in files
        assert "/lib/things/garage/sensors/__init__.py" in files
        assert "/lib/things/garage/sensors/door_open/__init__.py" in files

    def test_active_py_writes_dotted_form(self) -> None:
        """``active.py`` always carries the dotted name (boot's contract)."""
        files = boot_shim_files(thing_name="upstairs/bedroom_sensor")
        assert b'"upstairs.bedroom_sensor"' in files["/active.py"]


class TestBuildActivePyDotted:
    """Slice 2 — slash/dotted normalisation for nested thing names."""

    def test_slash_form_writes_dotted(self) -> None:
        body = build_active_py("upstairs/bedroom_sensor")
        assert 'THING_NAME = "upstairs.bedroom_sensor"' in body

    def test_dotted_form_writes_dotted(self) -> None:
        body = build_active_py("upstairs.bedroom_sensor")
        assert 'THING_NAME = "upstairs.bedroom_sensor"' in body

    def test_single_segment_unchanged(self) -> None:
        body = build_active_py("back-porch")
        assert 'THING_NAME = "back-porch"' in body


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


def _seed_nested_thing_for_boot(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    """Two-level nested thing fixture for boot-shim path tests."""
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n",
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: shh\n")
    thing_dir = tmp_path / "things" / "upstairs" / "bedroom_sensor"
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n",
    )
    (thing_dir / "app.py").write_text(
        "def run():\n    print('bedroom sensor running')\n",
    )
    return WorkspaceLayout(root=tmp_path), thing_dir


class TestThingBootSourceNested:
    """Slice 2 — nested thing-name plumbing through the boot source."""

    def test_files_land_under_nested_path(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_nested_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir,
            workspace=workspace,
            thing_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert (
            "/lib/things/upstairs/bedroom_sensor/app.py" in files
        )
        # Flat-layout path must NOT be present — that would shadow the
        # real on-device import.
        assert "/lib/things/bedroom_sensor/app.py" not in files

    def test_namespace_inits_emitted_per_level(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_nested_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir,
            workspace=workspace,
            thing_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert "/lib/things/__init__.py" in files
        assert "/lib/things/upstairs/__init__.py" in files
        assert "/lib/things/upstairs/bedroom_sensor/__init__.py" in files

    def test_active_py_carries_dotted_name(self, tmp_path: Path) -> None:
        workspace, thing_dir = _seed_nested_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir,
            workspace=workspace,
            thing_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert b'"upstairs.bedroom_sensor"' in files["/active.py"]

    def test_runtime_config_msgpack_at_canonical_path(self, tmp_path: Path) -> None:
        """Nested thing's msgpack still lands at /runtime_config.msgpack."""
        workspace, thing_dir = _seed_nested_thing_for_boot(tmp_path)
        source = thing_boot_source(
            thing_dir,
            workspace=workspace,
            thing_name="upstairs/bedroom_sensor",
        )
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi"]["password"] == "shh"

    def test_workspace_runtime_module_path_construction(self) -> None:
        """The boot module's ``things.<THING_NAME>.app`` import shape works for nested.

        ``workspace_runtime.boot()`` constructs the import path via
        string concatenation:

            module_path = "things." + thing_name + ".app"

        With a dotted ``THING_NAME = "upstairs.bedroom_sensor"`` the
        result is ``"things.upstairs.bedroom_sensor.app"`` — the path
        Python's ``__import__`` resolves through the namespace
        ``__init__.py`` chain.
        """
        thing_name = "upstairs.bedroom_sensor"
        module_path = "things." + thing_name + ".app"
        assert module_path == "things.upstairs.bedroom_sensor.app"


# ---------------------------------------------------------------------------
# multi_thing_boot_files — static shim layer for multi-thing layout
# ---------------------------------------------------------------------------


class TestMultiThingBootFiles:
    def test_registers_marker_for_every_thing(self) -> None:
        files = multi_thing_boot_files(
            active_thing_name="weather",
            thing_names=["weather", "heater", "diagnostic"],
        )
        assert "/lib/things/weather/__init__.py" in files
        assert "/lib/things/heater/__init__.py" in files
        assert "/lib/things/diagnostic/__init__.py" in files

    def test_active_py_names_only_active(self) -> None:
        files = multi_thing_boot_files(
            active_thing_name="weather",
            thing_names=["weather", "heater"],
        )
        assert b'"weather"' in files["/active.py"]
        assert b'"heater"' not in files["/active.py"]

    def test_main_py_override(self) -> None:
        files = multi_thing_boot_files(
            active_thing_name="weather",
            thing_names=["weather"],
            entrypoint_filename="main.py",
        )
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_dedup_thing_names(self) -> None:
        """Duplicate names collapse silently — convenience for caller-built lists."""
        files = multi_thing_boot_files(
            active_thing_name="weather",
            thing_names=["weather", "weather"],
        )
        # Only one __init__ entry; no crash from "duplicate dict key" semantics.
        assert "/lib/things/weather/__init__.py" in files

    def test_empty_thing_names_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one thing"):
            multi_thing_boot_files(active_thing_name="weather", thing_names=[])

    def test_active_not_in_thing_names_raises(self) -> None:
        with pytest.raises(ValueError, match="not in thing_names"):
            multi_thing_boot_files(
                active_thing_name="ghost",
                thing_names=["weather", "heater"],
            )

    def test_payload_at_canonical_path(self) -> None:
        files = multi_thing_boot_files(
            active_thing_name="weather",
            thing_names=["weather"],
        )
        assert BOOT_MODULE_DEVICE_PATH in files
        assert files[BOOT_MODULE_DEVICE_PATH] == load_workspace_runtime_payload()


# ---------------------------------------------------------------------------
# multi_thing_boot_source — host-side packager
# ---------------------------------------------------------------------------


def _seed_multi_thing_workspace(tmp_path: Path) -> tuple[WorkspaceLayout, list[Path]]:
    """Seed a workspace with two things ready for multi-thing deploy."""
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n"
    )
    (tmp_path / "secrets.yml").write_text(
        "wifi_password: shh\nheater_token: hot\n",
    )
    weather_dir = tmp_path / "things" / "weather"
    weather_dir.mkdir(parents=True)
    (weather_dir / "config.toml").write_text(
        "[wifi]\nssid = 'WeatherNet'\npassword = '!secret wifi_password'\n",
    )
    (weather_dir / "app.py").write_text(
        "def run():\n    print('weather running')\n",
    )

    heater_dir = tmp_path / "things" / "heater"
    heater_dir.mkdir(parents=True)
    (heater_dir / "config.toml").write_text(
        "[heater]\ntoken = '!secret heater_token'\n",
    )
    (heater_dir / "app.py").write_text(
        "def run():\n    print('heater running')\n",
    )

    return WorkspaceLayout(root=tmp_path), [weather_dir, heater_dir]


class TestMultiThingBootSource:
    def test_ships_every_thing_app(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(thing_dirs, workspace=workspace)
        files = source.files()
        assert "/lib/things/weather/app.py" in files
        assert "/lib/things/heater/app.py" in files

    def test_default_active_is_first_thing(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(thing_dirs, workspace=workspace)
        files = source.files()
        assert b'"weather"' in files["/active.py"]

    def test_explicit_active_overrides_default(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(
            thing_dirs, workspace=workspace, active_thing_name="heater",
        )
        files = source.files()
        assert b'"heater"' in files["/active.py"]

    def test_per_thing_msgpack_at_lib_path(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(thing_dirs, workspace=workspace)
        files = source.files()
        assert "/lib/things/weather/runtime_config.msgpack" in files
        assert "/lib/things/heater/runtime_config.msgpack" in files
        weather_decoded = unpackb(
            files["/lib/things/weather/runtime_config.msgpack"],
        )
        heater_decoded = unpackb(
            files["/lib/things/heater/runtime_config.msgpack"],
        )
        assert weather_decoded["wifi"]["password"] == "shh"
        assert heater_decoded["heater"]["token"] == "hot"

    def test_active_msgpack_at_canonical_path(self, tmp_path: Path) -> None:
        """Active thing's msgpack appears at /runtime_config.msgpack too."""
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(
            thing_dirs, workspace=workspace, active_thing_name="heater",
        )
        files = source.files()
        canonical = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        # Canonical msgpack matches the heater thing's merged config —
        # not the weather thing's.
        assert canonical["heater"]["token"] == "hot"
        # Thing-specific keys from the other thing don't bleed in.
        assert "ssid" not in canonical.get("wifi", {})

    def test_entrypoint_path(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(thing_dirs, workspace=workspace)
        assert source.entrypoint() == "/code.py"

    def test_main_py_entrypoint_for_micropython(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(
            thing_dirs, workspace=workspace, entrypoint_filename="main.py",
        )
        assert source.entrypoint() == "/main.py"
        assert "/main.py" in source.files()

    def test_empty_thing_dirs_raises(self, tmp_path: Path) -> None:
        workspace = WorkspaceLayout(root=tmp_path)
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        with pytest.raises(ValueError, match="at least one thing"):
            multi_thing_boot_source([], workspace=workspace)

    def test_duplicate_basenames_raise(self, tmp_path: Path) -> None:
        """Two thing_dirs whose basename collides — the user wrote the wrong path."""
        workspace, [weather_dir, _] = _seed_multi_thing_workspace(tmp_path)
        with pytest.raises(ValueError, match="duplicate thing names"):
            multi_thing_boot_source(
                [weather_dir, weather_dir], workspace=workspace,
            )

    def test_thing_names_length_mismatch_raises(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        with pytest.raises(ValueError, match="does not match"):
            multi_thing_boot_source(
                thing_dirs,
                workspace=workspace,
                thing_names=["only_one"],
            )

    def test_explicit_thing_names_override_basenames(self, tmp_path: Path) -> None:
        """Slice 2 — caller supplies slash-form names for nested deploys."""
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(
            thing_dirs,
            workspace=workspace,
            thing_names=["upstairs/weather", "garage/heater"],
            active_thing_name="upstairs/weather",
        )
        files = source.files()
        assert "/lib/things/upstairs/weather/app.py" in files
        assert "/lib/things/garage/heater/app.py" in files
        assert "/lib/things/upstairs/__init__.py" in files
        assert "/lib/things/garage/__init__.py" in files
        assert b'"upstairs.weather"' in files["/active.py"]

    def test_shared_namespace_init_dedup(self, tmp_path: Path) -> None:
        """Two siblings under the same namespace share one ``__init__.py``."""
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        source = multi_thing_boot_source(
            thing_dirs,
            workspace=workspace,
            thing_names=["upstairs/weather", "upstairs/heater"],
        )
        files = source.files()
        # Single shared init at the namespace level + two leaves.
        assert "/lib/things/upstairs/__init__.py" in files
        assert "/lib/things/upstairs/weather/__init__.py" in files
        assert "/lib/things/upstairs/heater/__init__.py" in files

    def test_active_not_in_thing_dirs_raises(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        with pytest.raises(ValueError, match="not in thing_dirs"):
            multi_thing_boot_source(
                thing_dirs, workspace=workspace, active_thing_name="ghost",
            )

    def test_missing_thing_config_raises_eagerly(self, tmp_path: Path) -> None:
        """Missing config.* in any thing dir surfaces before transport setup."""
        workspace, [weather_dir, _] = _seed_multi_thing_workspace(tmp_path)
        broken_dir = tmp_path / "things" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "app.py").write_text("def run(): pass\n")
        with pytest.raises(FileNotFoundError):
            multi_thing_boot_source(
                [weather_dir, broken_dir], workspace=workspace,
            )

    def test_extra_excluded_applied_to_each_thing(self, tmp_path: Path) -> None:
        workspace, thing_dirs = _seed_multi_thing_workspace(tmp_path)
        for thing_dir in thing_dirs:
            (thing_dir / "notes").mkdir()
            (thing_dir / "notes" / "draft.md").write_text("draft\n")
        source = multi_thing_boot_source(
            thing_dirs, workspace=workspace, extra_excluded=("notes",),
        )
        files = source.files()
        for thing_name in ("weather", "heater"):
            assert (
                f"/lib/things/{thing_name}/notes/draft.md" not in files
            )


# ---------------------------------------------------------------------------
# build_switch_files + switch_source — re-point /active.py only
# ---------------------------------------------------------------------------


class TestBuildSwitchFiles:
    def test_default_three_files(self) -> None:
        files = build_switch_files(
            thing_name="heater",
            runtime_config_msgpack=b"\xa4heat",
        )
        assert set(files) == {"/code.py", "/active.py", RUNTIME_CONFIG_DEVICE_PATH}

    def test_active_py_carries_thing_name(self) -> None:
        files = build_switch_files(
            thing_name="heater",
            runtime_config_msgpack=b"\xa4heat",
        )
        assert b'"heater"' in files["/active.py"]

    def test_msgpack_value_passed_through(self) -> None:
        files = build_switch_files(
            thing_name="heater",
            runtime_config_msgpack=b"\xa4heat",
        )
        assert files[RUNTIME_CONFIG_DEVICE_PATH] == b"\xa4heat"

    def test_main_py_override(self) -> None:
        files = build_switch_files(
            thing_name="heater",
            runtime_config_msgpack=b"\xa4heat",
            entrypoint_filename="main.py",
        )
        assert "/main.py" in files
        assert "/code.py" not in files

    def test_entrypoint_shim_is_canonical(self) -> None:
        files = build_switch_files(
            thing_name="heater",
            runtime_config_msgpack=b"",
        )
        assert files["/code.py"] == SHIM_ENTRYPOINT_SOURCE.encode("utf-8")


class TestSwitchSource:
    def test_files_match_build_switch_files(self, tmp_path: Path) -> None:
        workspace, [_, heater_dir] = _seed_multi_thing_workspace(tmp_path)
        source = switch_source(heater_dir, workspace=workspace)
        files = source.files()
        assert set(files) == {"/code.py", "/active.py", RUNTIME_CONFIG_DEVICE_PATH}

    def test_active_py_matches_thing_dir(self, tmp_path: Path) -> None:
        workspace, [_, heater_dir] = _seed_multi_thing_workspace(tmp_path)
        source = switch_source(heater_dir, workspace=workspace)
        assert b'"heater"' in source.files()["/active.py"]

    def test_msgpack_built_from_thing_config(self, tmp_path: Path) -> None:
        workspace, [_, heater_dir] = _seed_multi_thing_workspace(tmp_path)
        source = switch_source(heater_dir, workspace=workspace)
        decoded = unpackb(source.files()[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["heater"]["token"] == "hot"

    def test_main_py_entrypoint(self, tmp_path: Path) -> None:
        workspace, [_, heater_dir] = _seed_multi_thing_workspace(tmp_path)
        source = switch_source(
            heater_dir, workspace=workspace, entrypoint_filename="main.py",
        )
        assert source.entrypoint() == "/main.py"
        assert "/main.py" in source.files()
        assert "/code.py" not in source.files()

    def test_thing_name_override(self, tmp_path: Path) -> None:
        workspace, [_, heater_dir] = _seed_multi_thing_workspace(tmp_path)
        source = switch_source(
            heater_dir, workspace=workspace, thing_name="hottub",
        )
        assert b'"hottub"' in source.files()["/active.py"]

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        broken_dir = tmp_path / "things" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "app.py").write_text("def run(): pass\n")
        workspace = WorkspaceLayout(root=tmp_path)
        with pytest.raises(FileNotFoundError):
            switch_source(broken_dir, workspace=workspace)
