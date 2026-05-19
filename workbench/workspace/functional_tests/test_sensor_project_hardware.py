"""Hardware-gated tests for chumicro-workspace deploy mechanics.

Each test deploys the in-repo fixture project under
``fixtures/sensor_project/`` through the same import-graph +
workspace machinery that ``chumicro-workspace deploy`` uses.  The
fixture's ``app.py`` imports ``chumicro_kvstore``, so a successful
deploy proves four seams at once:

* ``project_import_graph_source`` walks the entrypoint, finds
  ``chumicro_kvstore`` transitively, and stages it onto the device.
* ``Deployer.deploy`` / ``deploy_diff`` resolves the on-device
  layout and runs the entrypoint.
* The runtime hands control off to the project's ``run()`` and
  captures stdout, so phase markers are readable from the host.
* On-device persistence (kvstore) survives a non-wipe deploy.

The fixture is self-contained — no reach into sibling chumicro
packages or other repos, no wifi / mqtt / broker round-trips.
Library-level integration tests (``libraries/mqtt/functional_tests/
test_real_broker.py`` and friends) own those seams.

Skips on:

* ``devices.yml`` missing or no matching runtime entry — real
  "no hardware available" case.
* ``deploy_mode != flash`` on the matched device — kvstore writes
  need a flash-backed filesystem / NVM region; RAM-mode deploys
  don't materialize files at the on-device root.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device, DeviceEntry
from chumicro_workspace.import_graph import project_import_graph_source
from chumicro_workspace.workspace import WorkspaceLayout

_FIXTURE_SOURCE = Path(__file__).parent / "fixtures" / "sensor_project"


def _chumicro_mono_repo_root() -> Path:
    """Mono-repo root: this file is three levels under it."""
    return Path(__file__).resolve().parents[3]


def _chumicro_library_search_paths() -> list[Path]:
    """Every ``<root>/libraries/<name>/src`` directory.

    The fixture imports ``chumicro_kvstore``; the import-graph
    walker needs each library's ``src/`` on its search path so the
    transitively-needed source files get shipped to the device.
    """
    libraries_dir = _chumicro_mono_repo_root() / "libraries"
    return sorted(
        path / "src"
        for path in libraries_dir.iterdir()
        if path.is_dir() and (path / "src").is_dir()
    )


def _build_device(entry: DeviceEntry) -> Device:
    """Translate a chumicro ``DeviceEntry`` into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode=entry.deploy_mode,
    )


def _stage_workspace(tmp_path: Path) -> tuple[WorkspaceLayout, Path]:
    """Materialize a tmp_path workspace whose ``projects/sensor_project/``
    is a copy of the in-repo fixture.  Returns (workspace, project_dir).
    """
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n"
        "  app_marker_prefix: fixture-sensor\n",
    )
    # `project_import_graph_source` composes runtime config from
    # `secrets.toml` + per-project `config.toml`; the secrets file must
    # exist even when the fixture has no secret keys.
    (tmp_path / "secrets.toml").write_text("")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_dir = projects_dir / "sensor_project"
    shutil.copytree(_FIXTURE_SOURCE, project_dir)
    return WorkspaceLayout(root=tmp_path), project_dir


def _skip_unless_flash_mode(entry: DeviceEntry) -> None:
    """Require flash-mode deploys: kvstore needs on-device persistence.

    Kvstore's runtime backends target the device's flash-backed
    filesystem (MP LittleFS, ESP32 NVS) or NVM region (CP).  RAM-mode
    deploys (``mpremote mount`` / inline-exec on CP) don't materialize
    files at the on-device root — they only map the host tmp dir under
    ``/remote`` — so kvstore can't reach its substrate.  Set
    ``defaults.deploy_mode: flash`` in devices.yml (or a per-device
    override) to enable.
    """
    if entry.deploy_mode != "flash":
        pytest.skip(
            f"fixture deploy test requires deploy_mode=flash; this "
            f"device is deploy_mode={entry.deploy_mode!r} — set "
            "defaults.deploy_mode: flash in devices.yml to enable.",
        )


def _assert_fixture_completed(execute_output: str) -> None:
    """Both phase markers from ``fixtures/sensor_project/app.py`` reached."""
    assert "fixture: boot #" in execute_output, (
        f"kvstore boot-counter print missing; got:\n{execute_output}"
    )
    assert "fixture: done" in execute_output, (
        f"fixture did not reach the done marker; got:\n{execute_output}"
    )


def test_sensor_project_deploys_on_micropython(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: workspace deploys the fixture and run() completes on-device."""
    _skip_unless_flash_mode(micropython_device)
    workspace, project_dir = _stage_workspace(tmp_path)
    device = _build_device(micropython_device)
    source = project_import_graph_source(
        project_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    # `deploy_diff(wipe=True)` reformats the device filesystem before
    # staging.  Without it, a prior test (e.g. the boot-shim suite) can
    # leave a colliding `/app.py` at the device root that resolves
    # before the fixture's `app.py` at `/lib/app.py`, causing the
    # entrypoint to run stale code from a previous deploy.  MP
    # transport's `deploy(clean=True)` is documented as `/lib`-only,
    # leaving root-level `/app.py` survivors — wipe is the right knob.
    result = Deployer(device).deploy_diff(source, wipe=True)
    _assert_fixture_completed(result.execute_output)


def test_sensor_project_deploys_on_circuitpython(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """CP: workspace deploys the fixture and run() completes on-device."""
    _skip_unless_flash_mode(circuitpython_device)
    workspace, project_dir = _stage_workspace(tmp_path)
    device = _build_device(circuitpython_device)
    source = project_import_graph_source(
        project_dir,
        workspace=workspace,
        entrypoint_filename="code.py",
        device_entrypoint="/code.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    # See the MP twin for why `deploy_diff(wipe=True)` is the right shape.
    result = Deployer(device).deploy_diff(source, wipe=True)
    _assert_fixture_completed(result.execute_output)


def test_sensor_project_kvstore_persists_across_deploys_on_micropython(
    micropython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """MP: kvstore boot counter advances between two deploys.

    First deploy wipes the filesystem so the kvstore starts fresh.
    Second preserves filesystem state, so a still-present kvstore
    blob means the counter has to advance.  Exact delta isn't
    asserted — deploy machinery soft-resets several times between
    captures and each reset bumps the counter.
    """
    _skip_unless_flash_mode(micropython_device)
    workspace, project_dir = _stage_workspace(tmp_path)
    device = _build_device(micropython_device)
    source = project_import_graph_source(
        project_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    deployer = Deployer(device)

    first = deployer.deploy_diff(source, wipe=True)
    _assert_fixture_completed(first.execute_output)

    second = deployer.deploy_diff(source)
    _assert_fixture_completed(second.execute_output)

    first_count = int(re.search(r"fixture: boot #(\d+)", first.execute_output).group(1))
    second_count = int(re.search(r"fixture: boot #(\d+)", second.execute_output).group(1))
    assert second_count > first_count, (
        f"boot counter did not advance: first={first_count} second={second_count}"
    )
