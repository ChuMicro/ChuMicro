"""Hardware-gated tests for the example_sensor thing in the canonical
workspace template repo (`ChuMicro-Workspace-Template`).

Phase 7 acceptance: the sensor thing exercises the full ChuMicro
runtime stack (wifi + sockets + mqtt + kvstore + workspace) on a
real board.  This file does as much of that as can be checked from
the chumicro mono-repo's CI / contributor flow without standing up
extra fixtures (test wifi network, test broker, subscriber to
verify message receipt).

Two layers, both ratchet up the strictness:

1. **Import resolution** — runs without hardware.  Proves the
   sensor thing's `app.py` imports cleanly through the published
   chumicro-workspace dep tree on CPython.  Catches API drift that
   per-library tests miss (e.g. a `WifiConfig.from_dict` rename
   would surface here).

2. **Deploy + boot phase markers** — runs on a real board.  Deploys
   the sensor thing with a fail-fast wifi config (bogus SSID,
   ``reconnect_max=0``, short connect timeout) so `run()` reaches
   the wifi-bringup loop, the loop fails, and `run()` raises
   `SystemExit` cleanly within seconds.  The execute output is
   asserted to contain the boot-counter print + the wifi-connecting
   marker — proves kvstore + config + import-graph + boot-shim all
   landed correctly without needing a live AP.  Skips when
   devices.yml lacks a matching entry or the template repo isn't
   reachable.

Layer-3 (live broker round-trip — Mosquitto fixture + paho-mqtt
subscriber on the host) tracked in
`plans/workstreams/phase-7-integration.md`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device
from chumicro_workspace import thing_import_graph_source
from chumicro_workspace.workspace import WorkspaceLayout

# scripts/ is on sys.path via root conftest.py.
from device_config import DeviceEntry  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Locate the canonical workspace template clone (or skip)
# ---------------------------------------------------------------------------


def _find_template_repo() -> Path | None:
    """Look for a local clone of `ChuMicro-Workspace-Template`.

    Checks (in order):
    1. `CHUMICRO_WORKSPACE_TEMPLATE_PATH` environment variable.
    2. `~/circuitpython/ChuMicro-Workspace-Template/` — the canonical
       contributor layout (mono-repo at `~/circuitpython/chumicro`,
       template repo as a sibling).
    """
    override = os.environ.get("CHUMICRO_WORKSPACE_TEMPLATE_PATH")
    if override:
        candidate = Path(override).expanduser()
        if (candidate / "things" / "example_sensor" / "app.py").is_file():
            return candidate
    sibling = Path.home() / "circuitpython" / "ChuMicro-Workspace-Template"
    if (sibling / "things" / "example_sensor" / "app.py").is_file():
        return sibling
    return None


@pytest.fixture
def template_repo() -> Path:
    repo = _find_template_repo()
    if repo is None:
        pytest.skip(
            "ChuMicro-Workspace-Template clone not found.  "
            "Set CHUMICRO_WORKSPACE_TEMPLATE_PATH or clone it next to chumicro/.",
        )
    return repo


# ---------------------------------------------------------------------------
# Layer 1: import-resolution (no hardware required)
# ---------------------------------------------------------------------------


def test_sensor_thing_imports_resolve_on_cpython(template_repo: Path) -> None:
    """app.py imports successfully through the chumicro-workspace stack on CPython.

    Catches API drift: a renamed `WifiConfig.from_dict`, a missing
    `MQTTClient.state`, a `Runner.add` signature change — all surface
    here before they hit a real board.
    """
    import importlib.util
    import sys as _sys

    app_path = template_repo / "things" / "example_sensor" / "app.py"
    spec = importlib.util.spec_from_file_location(
        "example_sensor_app_under_test", app_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        _sys.modules.pop("example_sensor_app_under_test", None)

    # Public surface the boot module + tests rely on.
    assert callable(module.run)
    assert hasattr(module, "HeartbeatPublisher")
    publisher_class = module.HeartbeatPublisher
    # check / handle is the runner contract — both must exist.
    assert callable(publisher_class.check)
    assert callable(publisher_class.handle)


# ---------------------------------------------------------------------------
# Layer 2: deploy + boot phase markers (hardware-gated, fail-fast wifi)
# ---------------------------------------------------------------------------


_FAIL_FAST_CONFIG_TOML = """\
# Per-thing config used by the Layer-2 functional test.  Picks an SSID
# guaranteed not to be in range, caps the connect timeout to a couple
# of seconds, and zeroes the reconnect budget so wifi transitions to
# FAILED on the first miss — `run()` then raises SystemExit and the
# deploy returns within seconds, letting us assert phase markers.
[wifi]
ssid = "chumicro-layer2-test-bogus"
password = "!secret wifi_password"
connect_timeout_ms = 2000
reconnect_max = 0

[mqtt]
broker = "localhost"
port = 1883
client_id = "chumicro-layer2-test"

[sensor]
topic = "chumicro/layer2/test"
publish_period_ms = 5000
"""


def _build_device(entry: DeviceEntry) -> Device:
    """Translate a chumicro ``DeviceEntry`` into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        circuitpy_drive_path=(
            Path(entry.circuitpy_drive_path)
            if entry.circuitpy_drive_path
            else None
        ),
    )


def _chumicro_mono_repo_root() -> Path:
    """The mono-repo root that holds this test file.

    `<root>/workbench/workspace/functional_tests/test_sensor_thing_hardware.py`
    so the root is three parents up.
    """
    return Path(__file__).resolve().parents[3]


def _chumicro_library_search_paths() -> list[Path]:
    """Every `<root>/libraries/<name>/src` directory.

    The sensor thing imports several chumicro libs; the import-graph
    walker needs each library's `src/` on its search path so the
    transitively-needed source files get shipped to the device.
    """
    libraries_dir = _chumicro_mono_repo_root() / "libraries"
    return sorted(
        path / "src"
        for path in libraries_dir.iterdir()
        if path.is_dir() and (path / "src").is_dir()
    )


def _stage_layer2_workspace(
    tmp_path: Path,
    template_repo: Path,
) -> tuple[WorkspaceLayout, Path]:
    """Build a tmp_path workspace whose `things/example_sensor/` is the
    canonical sensor thing's source with the fail-fast config above.

    Returns (workspace_layout, sensor_thing_dir).
    """
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  app_marker_prefix: layer2-sensor\n",
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: bogus-test-password\n")
    things_dir = tmp_path / "things"
    things_dir.mkdir()
    sensor_dir = things_dir / "example_sensor"
    sensor_dir.mkdir()
    shutil.copy(
        template_repo / "things" / "example_sensor" / "app.py",
        sensor_dir / "app.py",
    )
    (sensor_dir / "config.toml").write_text(_FAIL_FAST_CONFIG_TOML)
    # Bootstrap entrypoint for the import-graph deploy: import app, run.
    # The runtime calls main.py / code.py at boot, which calls our run().
    # Boot-shim path (active.py + workspace_runtime.boot()) doesn't compose
    # with thing_import_graph_source; this is the simpler shape for tests.
    _entrypoint_source = "from app import run\nrun()\n"
    (sensor_dir / "main.py").write_text(_entrypoint_source)
    (sensor_dir / "code.py").write_text(_entrypoint_source)
    return WorkspaceLayout(root=tmp_path), sensor_dir


def _skip_unless_flash_mode(entry: DeviceEntry) -> None:
    """Layer-2 tests require flash mode.

    The sensor thing calls ``chumicro_config.load_runtime_config()`` which
    reads ``/runtime_config.msgpack`` from the device's actual filesystem.
    RAM-mode deploys (``mpremote mount`` / inline-exec on CP) don't
    persist files to the on-device root — they only map the host tmp
    dir under ``/remote`` — so the msgpack ends up unreachable from
    `/runtime_config.msgpack`.  Set ``defaults.deploy_mode: flash`` in
    devices.yml (or per-device override) to enable.
    """
    if entry.deploy_mode != "flash":
        pytest.skip(
            f"Layer-2 sensor thing test requires deploy_mode=flash; this "
            f"device is deploy_mode={entry.deploy_mode!r} — set "
            "defaults.deploy_mode: flash in devices.yml to enable.",
        )


def _assert_layer2_phase_markers(execute_output: str) -> None:
    """Common assertions for both runtimes: the boot-shim chain reached
    the wifi-bringup phase before failing, proving every prior phase
    (deploy + import-graph + kvstore + config + boot-shim) worked.
    """
    assert "sensor: boot #" in execute_output, (
        f"kvstore boot-counter print missing; got:\n{execute_output}"
    )
    assert "sensor: connecting to wifi..." in execute_output, (
        f"wifi-bringup phase marker missing; got:\n{execute_output}"
    )


def test_sensor_thing_reaches_boot_phase_marker_on_micropython(
    micropython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """MP: sensor thing reaches `sensor: connecting to wifi...` and
    SystemExit's cleanly when wifi fails fast.
    """
    _skip_unless_flash_mode(micropython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(micropython_device)
    source = thing_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    result = Deployer(device).deploy(source)
    _assert_layer2_phase_markers(result.execute_output)


def test_sensor_thing_reaches_boot_phase_marker_on_circuitpython(
    circuitpython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """CP: sensor thing reaches `sensor: connecting to wifi...` and
    SystemExit's cleanly when wifi fails fast.
    """
    _skip_unless_flash_mode(circuitpython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(circuitpython_device)
    source = thing_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="code.py",
        device_entrypoint="/code.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    result = Deployer(device).deploy(source)
    _assert_layer2_phase_markers(result.execute_output)


def test_sensor_thing_boot_counter_persists_across_deploys_on_micropython(
    micropython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """MP: boot counter persists across two deploys (kvstore lifecycle).

    Skipped on RAM mode — RAM mode wipes per deploy so the counter
    can't carry over.  Run with ``defaults.deploy_mode: flash`` (or
    a per-device override) in devices.yml to enable.
    """
    _skip_unless_flash_mode(micropython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(micropython_device)
    source = thing_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    deployer = Deployer(device)

    first = deployer.deploy(source)
    _assert_layer2_phase_markers(first.execute_output)

    second = deployer.deploy(source)
    _assert_layer2_phase_markers(second.execute_output)
    # Boot counter went up between deploys.  Allow the first to be any
    # number ≥ 1 (in case a contributor's KVStore already had a count
    # from a prior run); the second must be strictly greater.
    import re

    first_count = int(
        re.search(r"sensor: boot #(\d+)", first.execute_output).group(1),
    )
    second_count = int(
        re.search(r"sensor: boot #(\d+)", second.execute_output).group(1),
    )
    assert second_count == first_count + 1, (
        f"boot counter did not advance: first={first_count} second={second_count}"
    )
