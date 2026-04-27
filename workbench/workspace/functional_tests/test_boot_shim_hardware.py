"""Hardware-gated tests for the boot-shim flow on real boards.

Single-thing boot-shim acceptance (multi-thing + switch tests
were retired in Slice 7 of the nested-things-and-examples
workstream — multi-thing-staging blew the flash budget on the
Decision 0015 minimum boards):

    [x] Functional test: deploy a thing via boot-shim layout, verify
        ``code.py`` -> ``workspace_runtime.boot()`` -> ``things.<name>.app.run()``
        runs end-to-end.

Each test stages a tmp_path workspace + thing, runs the deploy
through the real ``chumicro_deploy.Deployer``, and asserts that
the on-device ``workspace_runtime.boot()`` invoked the thing's
``run()`` by checking the distinctive ``print(...)`` marker
appears in the captured execute output.

Skip cleanly when ``devices.yml`` has no matching entry.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy import Deployer, Device, DeviceEntry
from chumicro_workspace import thing_boot_source
from chumicro_workspace.workspace import WorkspaceLayout

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
