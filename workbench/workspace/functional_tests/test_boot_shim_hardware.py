"""Hardware-gated tests for the boot-shim flow on real boards.

Single-project boot-shim acceptance (multi-project + switch tests
were retired in Slice 7 of the nested-projects-and-examples
workstream — multi-project-staging blew the flash budget on the
Decision 0015 minimum boards):

    [x] Functional test: deploy a project via boot-shim layout, verify
        ``code.py`` -> ``workspace_runtime.boot()`` -> ``projects.<name>.app.run()``
        runs end-to-end.

Each test stages a tmp_path workspace + project, runs the deploy
through the real ``chumicro_deploy.Deployer``, and asserts that
the on-device ``workspace_runtime.boot()`` invoked the project's
``run()`` by checking the distinctive ``print(...)`` marker
appears in the captured execute output.

Skip cleanly when ``devices.yml`` has no matching entry.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy import Deployer, Device, DeviceEntry
from chumicro_workspace import project_boot_source
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


def _seed_project(workspace_root: Path, *, name: str, marker: str) -> Path:
    """Create a project whose ``app.run()`` prints *marker* and returns."""
    project_dir = workspace_root / "projects" / name
    project_dir.mkdir(parents=True)
    (project_dir / "config.toml").write_text(f"[project]\nname = '{name}'\n")
    (project_dir / "app.py").write_text(
        # Keep the body MicroPython / CircuitPython compatible:
        # plain print + immediate return.
        f"def run():\n    print({marker!r})\n",
    )
    return project_dir


# ---------------------------------------------------------------------------
# Single-project boot-shim — both runtimes
# ---------------------------------------------------------------------------


def test_micropython_single_project_boot_runs_app(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: code.py -> workspace_runtime.boot() -> projects.solo.app.run() prints marker."""
    workspace = _seed_workspace(tmp_path)
    project_dir = _seed_project(tmp_path, name="solo", marker="MARKER-SOLO-MP")
    device = _build_device(micropython_device)
    source = project_boot_source(
        project_dir, workspace=workspace, entrypoint_filename="main.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-SOLO-MP" in result.execute_output


def test_circuitpython_single_project_boot_runs_app(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """CP: code.py -> workspace_runtime.boot() -> projects.solo.app.run() prints marker."""
    workspace = _seed_workspace(tmp_path)
    project_dir = _seed_project(tmp_path, name="solo", marker="MARKER-SOLO-CP")
    device = _build_device(circuitpython_device)
    source = project_boot_source(
        project_dir, workspace=workspace, entrypoint_filename="code.py",
    )
    result = Deployer(device).deploy(source)
    assert result.success, f"deploy failed: {result.traceback}"
    assert "MARKER-SOLO-CP" in result.execute_output
