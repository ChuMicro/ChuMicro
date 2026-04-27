"""Hardware-gated tests for the boot-shim flow on real boards.

Phase 4a Slice 7 + multi-thing follow-on acceptance:

    [ ] Functional test: deploy a thing via boot-shim layout, verify
        ``code.py`` -> ``workspace_runtime.boot()`` -> ``things.<name>.app.run()``
        runs end-to-end.
    [ ] Functional test: deploy multiple things side-by-side; the
        ``--active`` thing's ``run()`` is what executes.
    [ ] Functional test: ``switch <name>`` re-points ``/active.py``
        and the new thing runs on next boot.

Each test stages a tmp_path workspace + thing(s), runs the deploy
through the real ``chumicro_deploy.Deployer``, and asserts that
the on-device ``workspace_runtime.boot()`` invoked the chosen
thing's ``run()`` by checking that the thing's distinctive
``print(...)`` marker appears in the captured execute output.

Skip cleanly when ``devices.yml`` has no matching entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device, DeviceEntry
from chumicro_workspace import (
    multi_thing_boot_source,
    switch_source,
    thing_boot_source,
)
from chumicro_workspace.workspace import WorkspaceLayout


def _skip_if_ram_mode(entry: DeviceEntry) -> None:
    """Switch tests need persistent on-device files between deploys.

    RAM-mode deploys exec everything inline without persisting to flash —
    each deploy is a clean session, so a follow-up switch_source deploy
    can't find the workspace_runtime payload that the prior multi-thing
    deploy "shipped".  These tests only exercise the switch flow when
    deploy_mode is ``flash``.  Set ``defaults.deploy_mode: flash`` in
    devices.yml (or override per-device) to run them.
    """
    if entry.deploy_mode != "flash":
        pytest.skip(
            f"switch tests require deploy_mode=flash; this device is "
            f"deploy_mode={entry.deploy_mode!r} — set "
            "defaults.deploy_mode: flash in devices.yml to enable.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_device(entry: DeviceEntry) -> Device:
    """Translate a chumicro ``DeviceEntry`` into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        circuitpy_drive_path=(
            Path(entry.circuitpy_drive_path) if entry.circuitpy_drive_path else None
        ),
    )


def _seed_workspace(tmp_path: Path) -> WorkspaceLayout:
    """Create a minimal workspace.yml + secrets.yml under *tmp_path*."""
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  app_marker_prefix: chu-bootshim\n",
    )
    (tmp_path / "secrets.yml").write_text("dummy: ok\n")
    return WorkspaceLayout(root=tmp_path)


def _seed_thing(workspace_root: Path, *, name: str, marker: str) -> Path:
    """Create a thing whose ``app.run()`` prints *marker* and returns."""
    thing_dir = workspace_root / "things" / name
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(f"[thing]\nname = '{name}'\n")
    (thing_dir / "app.py").write_text(
        # Keep the body MicroPython / CircuitPython compatible:
        # plain print + immediate return.
        f"def run():\n    print({marker!r})\n",
    )
    return thing_dir


# ---------------------------------------------------------------------------
# Single-thing boot-shim — both runtimes
# ---------------------------------------------------------------------------


def test_micropython_single_thing_boot_runs_app(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: code.py -> workspace_runtime.boot() -> things.solo.app.run() prints marker."""
    workspace = _seed_workspace(tmp_path)
    thing_dir = _seed_thing(tmp_path, name="solo", marker="MARKER-SOLO-MP")
    device = _build_device(micropython_device)
    source = thing_boot_source(
        thing_dir, workspace=workspace, entrypoint_filename="main.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-SOLO-MP" in result.execute_output


def test_circuitpython_single_thing_boot_runs_app(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """CP: code.py -> workspace_runtime.boot() -> things.solo.app.run() prints marker."""
    workspace = _seed_workspace(tmp_path)
    thing_dir = _seed_thing(tmp_path, name="solo", marker="MARKER-SOLO-CP")
    device = _build_device(circuitpython_device)
    source = thing_boot_source(
        thing_dir, workspace=workspace, entrypoint_filename="code.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-SOLO-CP" in result.execute_output


# ---------------------------------------------------------------------------
# Multi-thing — both runtimes
# ---------------------------------------------------------------------------


def test_micropython_multi_thing_active_runs(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: with two things deployed, only the --active one runs."""
    workspace = _seed_workspace(tmp_path)
    weather = _seed_thing(tmp_path, name="weather", marker="MARKER-WEATHER-MP")
    heater = _seed_thing(tmp_path, name="heater", marker="MARKER-HEATER-MP")
    device = _build_device(micropython_device)
    source = multi_thing_boot_source(
        [weather, heater],
        workspace=workspace,
        active_thing_name="heater",
        entrypoint_filename="main.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-HEATER-MP" in result.execute_output
    # Only the active thing's run() fires; the inactive one stays silent.
    assert "MARKER-WEATHER-MP" not in result.execute_output


def test_circuitpython_multi_thing_active_runs(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """CP: with two things deployed, only the --active one runs."""
    workspace = _seed_workspace(tmp_path)
    weather = _seed_thing(tmp_path, name="weather", marker="MARKER-WEATHER-CP")
    heater = _seed_thing(tmp_path, name="heater", marker="MARKER-HEATER-CP")
    device = _build_device(circuitpython_device)
    source = multi_thing_boot_source(
        [weather, heater],
        workspace=workspace,
        active_thing_name="heater",
        entrypoint_filename="code.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-HEATER-CP" in result.execute_output
    assert "MARKER-WEATHER-CP" not in result.execute_output


# ---------------------------------------------------------------------------
# Switch — both runtimes
# ---------------------------------------------------------------------------


def test_micropython_switch_runs_new_active(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: switch from active=weather to heater; second deploy runs heater."""
    _skip_if_ram_mode(micropython_device)
    workspace = _seed_workspace(tmp_path)
    weather = _seed_thing(tmp_path, name="weather", marker="MARKER-W-SWITCH-MP")
    heater = _seed_thing(tmp_path, name="heater", marker="MARKER-H-SWITCH-MP")
    device = _build_device(micropython_device)

    # Initial multi-thing deploy with active=weather.
    multi_source = multi_thing_boot_source(
        [weather, heater],
        workspace=workspace,
        active_thing_name="weather",
        entrypoint_filename="main.py",
    )
    initial = Deployer(device).deploy(multi_source)
    assert initial.success, f"initial deploy failed: {initial.traceback}"
    assert "MARKER-W-SWITCH-MP" in initial.execute_output

    # Switch to heater — only ships /main.py + /active.py + msgpack.
    switch = switch_source(heater, workspace=workspace, entrypoint_filename="main.py")
    after = Deployer(device).deploy(switch)
    assert after.success, f"switch deploy failed: {after.traceback}"
    assert "MARKER-H-SWITCH-MP" in after.execute_output
    # Switch ships only the three switch files — no thing payloads.
    assert sorted(after.staged_files) == sorted(switch.files().keys())


def test_circuitpython_switch_runs_new_active(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """CP: switch from active=weather to heater; second deploy runs heater."""
    _skip_if_ram_mode(circuitpython_device)
    workspace = _seed_workspace(tmp_path)
    weather = _seed_thing(tmp_path, name="weather", marker="MARKER-W-SWITCH-CP")
    heater = _seed_thing(tmp_path, name="heater", marker="MARKER-H-SWITCH-CP")
    device = _build_device(circuitpython_device)

    multi_source = multi_thing_boot_source(
        [weather, heater],
        workspace=workspace,
        active_thing_name="weather",
        entrypoint_filename="code.py",
    )
    initial = Deployer(device).deploy(multi_source)
    assert initial.success, f"initial deploy failed: {initial.traceback}"
    assert "MARKER-W-SWITCH-CP" in initial.execute_output

    switch = switch_source(heater, workspace=workspace, entrypoint_filename="code.py")
    after = Deployer(device).deploy(switch)
    assert after.success, f"switch deploy failed: {after.traceback}"
    assert "MARKER-H-SWITCH-CP" in after.execute_output
    assert sorted(after.staged_files) == sorted(switch.files().keys())
